# -*- coding: utf-8 -*-
"""
Copyright (c)  2016 HUAWEI TECHNOLOGIES CO.,LTD and others. All rights reserved.

The MIT License (MIT)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
# __all__ = ["HuaweiExprStarter"]

import sys

sys.path.append("..")
from compiler.ast import flatten
from threading import Lock

from docker_expr_starter import DockerExprStarter
from hackathon import RequiredFeature, Context
from hackathon.hmongo.models import Hackathon, Experiment, DockerContainer, PortBinding, DockerHostServer, AzureKey
from hackathon.constants import DHS_QUERY_STATE, EStatus, AVMStatus, VERemoteProvider, VEStatus
from hackathon.template import DOCKER_UNIT

FEATURE = "huawei_docker"
IN_PROGRESS = 'InProgress'
SUCCEEDED = 'Succeeded'
MAX_TRIAL = 20
TRIAL_INTERVAL_SECONDS = 3
DEPLOYMENT_SLOT = "Production"

class HuaweiExprStarter(DockerExprStarter):
    docker = RequiredFeature("huawei_docker_proxy")
    docker_host_manager = RequiredFeature("docker_host_manager")
    host_ports = []
    host_port_max_num = 30

    def _internal_start_virtual_environment(self, context):
        self.get_docker_host_server(context)

    def _get_docker_proxy(self):
        return self.docker

    def get_docker_host_server(self, context):
        # TODO: currently do nothing
        hackathon = Hackathon.objects(id=context.hackathon_id).no_dereference().first()
        try:
            host_resp = self.docker_host_manager.get_available_docker_host(hackathon)
        except Exception as e:  # if not succeeded, scheduler would rerun this function
            self.log.error(e)
            host_resp = Context(state=DHS_QUERY_STATE.ONGOING)

        context.trial = context.get("trial", 0) + 1
        if host_resp.state == DHS_QUERY_STATE.SUCCESS:
            # start successfully, context will contains a DockerHostServer object
            # and assign ports
            self.__assign_ports(context, host_resp.docker_host_server)
        elif host_resp.state == DHS_QUERY_STATE.ONGOING and context.trial < MAX_TRIAL:
            # tried up to 20 times
            self.log.debug("host servers are all busy, %d times tried, will retry in %d seconds" %
                           (context.trial, TRIAL_INTERVAL_SECONDS))
            self.scheduler.add_once(FEATURE, "get_docker_host_server", context, seconds=TRIAL_INTERVAL_SECONDS)
        else:
            self.log.error("no available host server")
            self._on_virtual_environment_failed(context)

    def __assign_ports(self, context, host_server):
        self.log.debug("try to assign port on server %r" % host_server)
        unit = context.unit
        experiment = Experiment.objects(id=context.experiment_id).no_dereference().first()
        virtual_environment = experiment.virtual_environments.get(name=context.virtual_environment_name)
        container = DockerContainer(name=virtual_environment.name,
                                    image=unit.get_image_with_tag(),
                                    host_server=host_server,
                                    port_bindings=[])
        virtual_environment.docker_container = container
        experiment.save()

        context.container_name = container.name
        self.__assign_host_ports(context, host_server)
        self._hooks_on_virtual_environment_success(context)

    def __assign_host_ports(self, context, host_server):
        """assign ports that map a port on docker host server to a port inside docker"""
        unit = context.unit
        # assign host port
        try:
            port_cfg = unit.get_ports()
            for cfg in port_cfg:
                cfg[DOCKER_UNIT.PORTS_HOST_PORT] = self.__get_available_host_port(host_server,
                                                                                  cfg[DOCKER_UNIT.PORTS_PORT])
            context.port_config = port_cfg
            self.__assign_public_ports(context, host_server)
        except Exception as e:
            self.log.error(e)
            self._on_virtual_environment_failed(context)

    def __get_available_host_port(self, docker_host, private_port):
        """
        We use double operation to ensure ports not conflicted, first we get ports from host machine, but in multiple
        threads situation, the interval between two requests is too short, maybe the first thread do not get port
        ended, so the host machine don't update ports in time, thus the second thread may get the same port.
        To avoid this condition, we use static variable host_ports to cache the latest host_port_max_num ports.
        Every thread visit variable host_ports is synchronized.
        To save space, we will release the ports if the number over host_port_max_num.
        :param docker_host:
        :param private_port:
        :return:
        """
        self.log.debug("try to assign docker port %d on server %r" % (private_port, docker_host))
        containers = self.docker.list_containers(docker_host)
        used_host_ports = flatten(map(lambda p: p['Ports'], containers))

        # todo if azure return -1
        def sub(port):
            return port["PublicPort"] if "PublicPort" in port else -1

        used_public_ports = map(lambda x: sub(x), used_host_ports)
        return self.__safe_get_host_port(used_public_ports, private_port)

    def __assign_public_ports(self, context, host_server):
        """assign ports on azure cloud service that map a public port to a port inside certain VM"""
        port_cfg = context.port_config
        context.host_server_id = host_server.id

        if self.util.is_local():
            for cfg in port_cfg:
                cfg[DOCKER_UNIT.PORTS_PUBLIC_PORT] = cfg[DOCKER_UNIT.PORTS_HOST_PORT]
            self.__update_virtual_environment_cfg(context)
        else:
            # configure ports on azure cloud service
            vm_adapter = self.__get_azure_vm_adapter(context)
            virtual_machine_name = host_server.vm_name
            cloud_service_name = host_server.public_dns.split('.')[0]  # cloud_service_name.chinacloudapp.cn

            # filter the port config with "public" True
            self.log.debug("starting to assign azure ports...")
            public_ports_cfg = filter(lambda p: DOCKER_UNIT.PORTS_PUBLIC in p, port_cfg)
            host_ports = [u[DOCKER_UNIT.PORTS_HOST_PORT] for u in public_ports_cfg]

            # get assigned ports of cloud service
            assigned_endpoints = vm_adapter.get_assigned_endpoints(cloud_service_name)
            if not assigned_endpoints:
                self.log.debug('fail to assign endpoints: %s' % cloud_service_name)
                self._on_virtual_environment_failed(context)
                return

            endpoints_to_assign = find_unassigned_endpoints(host_ports, assigned_endpoints)
            # duplication detection for public endpoint
            deployment_name = vm_adapter.get_deployment_name(cloud_service_name, DEPLOYMENT_SLOT)
            network_config = vm_adapter.get_virtual_machine_network_config(cloud_service_name,
                                                                           deployment_name,
                                                                           virtual_machine_name)
            new_network_config = add_endpoint_to_network_config(network_config, endpoints_to_assign, host_ports)
            try:
                result = vm_adapter.update_virtual_machine_network_config(cloud_service_name,
                                                                          deployment_name,
                                                                          virtual_machine_name,
                                                                          new_network_config)
                context.request_id = result.request_id
            except Exception as e:
                self.log.error(e)
                self.log.error('fail to assign endpoints: %s' % endpoints_to_assign)
                self._on_virtual_environment_failed(context)
                return

            updated_config = []
            for cfg in context.port_config:
                if cfg[DOCKER_UNIT.PORTS_HOST_PORT] in host_ports:
                    index = host_ports.index(cfg[DOCKER_UNIT.PORTS_HOST_PORT])
                    cfg[DOCKER_UNIT.PORTS_PUBLIC_PORT] = endpoints_to_assign[index]
                updated_config.append(cfg)
            context.port_config = updated_config

            # query azure to make sure the network config updated
            context.virtual_machine_name = virtual_machine_name
            context.cloud_service_name = cloud_service_name
            context.trial = 0
            self.query_network_config_status(context)