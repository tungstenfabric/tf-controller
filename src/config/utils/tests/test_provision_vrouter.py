#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#
import logging
import os
import sys

from vnc_api.gen.resource_xsd import KeyValuePair
from vnc_api.gen.resource_xsd import KeyValuePairs

from .test_case import UtilsTestCase

sys.path.append("%s/.." % os.path.dirname(__file__))
import provision_vrouter # noqa

logger = logging.getLogger(__name__)


class TestProvisionVrouter(UtilsTestCase):
    @classmethod
    def setUpClass(cls, *args, **kwargs):
        cls.console_handler = logging.StreamHandler()
        cls.console_handler.setLevel(logging.DEBUG)
        logger.addHandler(cls.console_handler)
        super(TestProvisionVrouter, cls).setUpClass(*args, **kwargs)

    @classmethod
    def tearDownClass(cls, *args, **kwargs):
        logger.removeHandler(cls.console_handler)
        super(TestProvisionVrouter, cls).tearDownClass(*args, **kwargs)

    def test_add_virtual_router(self):
        name = "localhost-%s" % self.id()
        physnet_mapping = {"physnet1": "eth0", "physnet2": "eth1"}
        prov_args = [
            "--host_ip 127.0.0.1",
            "--host_name %s" % name,
            "--ip_fabric_subnet 10.1.1.0/28",
            "--api_server_ip %s" % self._server_info['ip'],
            "--api_server_port %s" % self._server_info['service_port'],
            "--sriov_physnets %s" % ' '.join(
                [k + '=' + v for k, v in physnet_mapping.items()]),
        ]

        provision_vrouter.VrouterProvisioner(args_str=' '.join(prov_args))

        fq_name = ['default-global-system-config', name]
        vrouter_obj = self.api.virtual_router_read(fq_name)
        physnets = (vrouter_obj.get_virtual_router_sriov_physical_networks() or
                    KeyValuePairs())
        physnet_kvps = physnets.get_key_value_pair() or []
        for physnet, interface in physnet_mapping.items():
            kvp = KeyValuePair(key=physnet, value=interface)
            assert kvp in physnet_kvps,\
                "(%s) kv pair not found in physnet kvps (%s)" % (
                    kvp, physnet_kvps)
