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

import sys

__all__ = ["HuaweiDockerFormation"]

sys.path.append("..")
import requests
import json
from datetime import datetime, timedelta

from docker_formation_base import DockerFormationBase
from hackathon.constants import HEALTH_STATUS, VE_PROVIDER, VEStatus, EStatus, HEALTH, OAUTH_PROVIDER
from hackathon.hmongo.models import VirtualEnvironment
from hackathon.hackathon_exception import AlaudaException
from hackathon.template import DOCKER_UNIT
from hackathon import Component, Context, RequiredFeature


class HUAWEI:
    IS_DEPLOYING = "is_deploying"
    CURRENT_STATUS = "current_status"
    RUNNING = "Running"
    CONTAINER_PORT = "container_port"
    INSTANCE_PORTS = "instance_ports"
    DEFAULT_DOMAIN = "default_domain"
    SERVICE_PORT = "service_port"


class HuaweiDockerFormation(DockerFormationBase, Component):
    user_manager = RequiredFeature("user_manager")
    expr_manager = RequiredFeature("expr_manager")

    def stop(self, name, **kwargs):
        super(HuaweiDockerFormation, self).stop(name, **kwargs)

    def delete(self, name, **kwargs):
        super(HuaweiDockerFormation, self).delete(name, **kwargs)

    def report_health(self):
        super(HuaweiDockerFormation, self).report_health()

    def start(self, unit, **kwargs):
        virtual_environment = kwargs["virtual_environment"]
        user = virtual_environment.experiment.user

        virtual_environment.provider = VE_PROVIDER.HUAWEI
        self.db.commit()

        service_config = self.__get_service_config(unit)
        self.__create_service(user, service_config)

        service_name = unit.get_name()
        service = self.__query_service(user, service_name)
        # service = {}

        context = Context(guacamole=unit.get_remote(),
                          service_name=service_name,
                          user_id=user.id,
                          virtual_environment_id=virtual_environment.id,
                          ve_remote_paras=virtual_environment.remote_paras)
        self.__service_result_handler(service, context)
        return service

##################  private functions ##############################
    def __get_default_service_config(self):
        default_service_config = {
            "service_name": "",
            "image_name": "",
            "image_tag": "latest",
            "run_command": "",
            "instance_size": "XS",
            "scaling_mode": "MANUAL",
            "target_state": "STARTED",
            "custom_domain_name": "",
            "linked_to_apps": "{}",
            "target_num_instances": "1",
            "region_name": self.util.safe_get_config("docker.alauda.region_name", "SHANGHAI1"),
            "instance_envvars": {},
            "instance_ports": [],
            "volumes": []  # todo volumes not implemented for now
        }
        return default_service_config

    def __get_service_config(self, unit):
        service_config = self.__get_default_service_config()
        service_config["service_name"] = unit.get_name()
        service_config["image_name"] = unit.get_image_without_tag()
        service_config["image_tag"] = unit.get_tag()
        service_config["run_command"] = unit.get_run_command()
        service_config["instance_envvars"] = unit.get_instance_env_vars()
        service_config["instance_ports"] = unit.get_instance_ports()
        return service_config

    def __create_service(self, user, service_config):
        # TODO create service
        # TODO determine what is service
        pass