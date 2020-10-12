import unittest
import sys

from fake_cc_client import FakeCCClient, CreateAcceptRequest, GetAcceptRequest
from assert_dictionaries import assert_subset_dictionaries

sys.path.append('/opt/contrail/fabric_ansible_playbooks/filter_plugins')
from import_server import FilterModule


class TestImportNodes(unittest.TestCase):
    def test_none(self):
        fm = FilterModule()
        client = FakeCCClient([])

        fm.import_nodes(None, client)

    def test_empty_dict(self):
        fm = FilterModule()
        client = FakeCCClient([])

        data = {}

        fm.import_nodes({}, client)

    def test_single_node_without_ports(self):
        node_name = "green-node"

        data = {
            "nodes": [{
                "name": node_name,
                "node_type": "ovs-compute",
            }]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={},
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_empty_ports_list(self):
        node_name = "green-node"

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": "ovs-compute",
                    "ports": []
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={},
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_single_port(self):
        data = {
            "nodes": [
                {
                    "name": "node-1",
                    "node_type": "ovs-compute",
                    "ports": [
                        {
                            "name": "ens224",
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00"
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={},
                response=self.__get_node_create_response_content(
                    name='node-1',
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": 'ens224',
                                "parent_type": "node"
                            }
                          }]
                         },
                response=self.__get_port_response_content(
                    name='ens224',
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        response = FilterModule().import_nodes(data, client)

        client.assert_results()

    def test_single_node_with_multiple_ports(self):
        node_name = "green-node"
        green_port_name = "ens224"
        blue_port_name = "ens227"

        node_type = "ovs-compute"

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": green_port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00"
                        },
                        {
                            "name": blue_port_name,
                            "mac_address": "00:0c:29:13:37:cc",
                            "switch_name": "VM283DD71D11"
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": node_name,
                                "parent_type": "global-system-config"
                            }
                          }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                                "kind": "port",
                                "data": {
                                    "name": green_port_name,
                                    "parent_type": "node"
                                }
                            }, {
                                "kind": "port",
                                "data": {
                                    "name": blue_port_name,
                                    "parent_type": "node"
                                }
                            }]
                         },
                response=self.__get_port_response_content(
                    name=green_port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_existing_node_will_update(self):
        green_node_name = "green-node"
        green_node_uuid = "beefbeef-beef-beef-beef-beefbeef1111"
        node_type = "baremetal"

        data = {
            "nodes": [{
                "name": green_node_name,
                "node_type": node_type,
            }]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": [
                    {
                        "node": {
                            "name": green_node_name,
                            "fq_name": ["default-global-system-config",
                                        green_node_name],
                            "parent_type": "global-system-config",
                            "uuid": green_node_uuid,
                            "node_type": "ovs-compute"
                        }
                    }, {
                        "node": {
                            "name": "red-node",
                            "fq_name": ["default-global-system-config",
                                        "red-node"],
                            "parent_type": "global-system-config",
                            "uuid": "beefbeef-beef-beef-beef-beefbeef2222",
                            "node_type": "ovs-compute"
                        }
                    }, {
                        "node": {
                            "name": "blue-node",
                            "fq_name": ["default-global-system-config",
                                        "blue-node"],
                            "parent_type": "global-system-config",
                            "uuid": "beefbeef-beef-beef-beef-beefbeef3333",
                            "node_type": "ovs-compute"
                        }
                    }
                ]}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                                "kind": "node",
                                "data": {
                                    "node_type": node_type,
                                    "name": green_node_name,
                                    "uuid": green_node_uuid,
                                    "parent_type": "global-system-config"
                                }
                            }]
                         },
                response=self.__get_node_create_response_content(
                    name=green_node_name,
                    uuid=green_node_uuid
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "baremetal",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": "beefbeef-beef-beef-beef-beefbeef1111"
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_existing_node_with_new_ports(self):
        unittest.skip(
            "Updating existing node with existing ports does not update ports"
        )

    def test_single_node_with_single_port_with_empty_tag_list(self):
        node_name = "green-node"
        node_type = "baremetal"
        port_name = "green-port"

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00",
                            "tags": []
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": port_name,
                                "parent_type": "node",
                                "parent_uuid": "beefbeef-beef-beef-beef-"
                                               "beefbeef1111"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "baremetal",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_single_port_with_single_nonexisting_tag(self):
        node_name = "green-node"
        node_type = "baremetal"
        port_name = "green-port"
        tag_value = "management-port"

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00",
                            "tags": [tag_value]
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "tag",
                            "data": {
                                "tag_type_name": "label",
                                "tag_value": tag_value,
                                "name": '{}={}'.format("label", tag_value),
                                "fq_name": ['{}={}'.format("label",
                                                           tag_value)],

                            }
                         }]
                         },
                response=self.__get_tag_response_content(
                    value=tag_value,
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": port_name,
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "baremetal",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_single_port_with_single_existing_tag(self):
        node_name = "green-node"
        node_type = "baremetal"
        port_name = "green-port"
        tag_value = "management-port"

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00",
                            "tags": [tag_value]
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": [
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_value,
                            "name": '{}={}'.format("label", tag_value),
                            "fq_name": ['{}={}'.format("label", tag_value)],
                        }
                    }
                ]}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": port_name,
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "baremetal",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_single_port_with_multiple_tags(self):
        node_name = "green-node"
        node_type = "baremetal"
        port_name = "green-port"
        tag_values = ["management-port", "other-tag", "some-tag"]

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00",
                            "tags": tag_values
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": [
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[0],
                            "name": '{}={}'.format("label", tag_values[0]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[0])],
                        }
                    },
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[1],
                            "name": '{}={}'.format("label", tag_values[1]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[1])],
                        }
                    },
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[2],
                            "name": '{}={}'.format("label", tag_values[2]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[2])],
                        }
                    }
                ]}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": port_name,
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "baremetal",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_multiple_ports_with_multiple_tags(self):
        node_name = "green-node"
        node_type = "baremetal"
        tag_values = ["management-port", "other-tag", "some-tag"]

        data = {
            "nodes": [
                {
                    "name": node_name,
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": "green-port",
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00",
                            "tags": tag_values[:2]
                        },
                        {
                            "name": "blue-port",
                            "mac_address": "00:0c:29:13:37:cc",
                            "switch_name": "VM283DD71D00",
                            "tags": tag_values[1:]
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": [
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[0],
                            "name": '{}={}'.format("label", tag_values[0]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[0])],
                        }
                    },
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[1],
                            "name": '{}={}'.format("label", tag_values[1]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[1])],
                        }
                    },
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[2],
                            "name": '{}={}'.format("label", tag_values[2]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[2])],
                        }
                    }
                ]}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": 'green-port',
                                "parent_type": "node"
                            }
                         },
                            {
                                "kind": "port",
                                "data": {
                                    "name": 'blue-port',
                                    "parent_type": "node"
                                }
                            }]
                         },
                response=self.__get_port_response_content(
                    name='green-port',
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "baremetal",
                            "display_name": "green-node",
                            "name": "green-node",
                            "fq_name": [
                                "default-global-system-config",
                                "green-node"
                            ],
                            "hostname": "green-node",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "green-node",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_multiple_nodes_without_ports(self):
        red_node_name = "node-red"
        green_node_name = "node-green"
        blue_node_name = "node-blue"
        node_type = "ovs-compute"

        data = {
            "nodes": [
                {
                    "name": red_node_name,
                    "node_type": node_type
                },
                {
                    "name": green_node_name,
                    "node_type": node_type
                },
                {
                    "name": blue_node_name,
                    "node_type": node_type
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": red_node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=red_node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": green_node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=green_node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": blue_node_name,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=blue_node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef3333"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "node-red",
                            "name": "node-red",
                            "fq_name": [
                                "default-global-system-config",
                                "node-red"
                            ],
                            "hostname": "node-red",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "node-red",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            },
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "node-green",
                            "name": "node-green",
                            "fq_name": [
                                "default-global-system-config",
                                "node-green"
                            ],
                            "hostname": "node-green",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "node-green",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            },
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "node-blue",
                            "name": "node-blue",
                            "fq_name": [
                                "default-global-system-config",
                                "node-blue"
                            ],
                            "hostname": "node-blue",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "node-blue",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))

        client.assert_results()

    def test_single_node_with_name_from_mac_address(self):
        node_name = "green_node"
        green_port_name = "ens224"
        blue_port_name = "ens227"

        node_type = "ovs-compute"

        data = {
            "nodes": [
                {
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": green_port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00"
                        },
                        {
                            "name": blue_port_name,
                            "mac_address": "00:0c:29:13:37:cc",
                            "switch_name": "VM283DD71D11"
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": green_port_name,
                                "parent_type": "node"
                            }
                         }, {
                            "kind": "port",
                            "data": {
                                "name": blue_port_name,
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=green_port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": "auto-1337bb",
                            "name": "auto-1337bb",
                            "fq_name": [
                                "default-global-system-config",
                                "auto-1337bb"
                            ],
                            "hostname": "auto-1337bb",
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": "auto-1337bb",
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))
        self.assertEqual(len(response), 1)

        client.assert_results()

    def test_single_node_with_name_from_hostname(self):
        host_name = "green_node"
        green_port_name = "ens224"
        blue_port_name = "ens227"

        node_type = "ovs-compute"

        data = {
            "nodes": [
                {
                    "node_type": node_type,
                    "hostname": host_name,
                    "ports": [
                        {
                            "name": green_port_name,
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D00"
                        },
                        {
                            "name": blue_port_name,
                            "mac_address": "00:0c:29:13:37:cc",
                            "switch_name": "VM283DD71D11"
                        }
                    ]
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=host_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": green_port_name,
                                "parent_type": "node"
                            }
                         }, {
                            "kind": "port",
                            "data": {
                                "name": blue_port_name,
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=green_port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = [
            {
                "resources": [
                    {
                        "kind": "node",
                        "data": {
                            "node_type": "ovs-compute",
                            "display_name": host_name,
                            "name": host_name,
                            "fq_name": [
                                "default-global-system-config",
                                host_name
                            ],
                            "hostname": host_name,
                            "parent_type": "global-system-config",
                            "bms_info": {
                                "name": host_name,
                                "driver_info": {},
                                "driver": "pxe_ipmitool",
                                "type": "baremetal",
                                "properties": {},
                                "network_interface": "neutron"
                            },
                            "uuid": None
                        }
                    }
                ]
            }
        ]

        response = FilterModule().import_nodes(data, client)

        self.assertTrue(assert_subset_dictionaries(expected_response[0],
                                                   response[0]))
        self.assertEqual(len(response), 1)

        client.assert_results()

    def test_single_node_with_no_name(self):
        node_name = "green_node"
        green_port_name = "ens224"
        blue_port_name = "ens227"

        node_type = "ovs-compute"

        data = {
            "nodes": [
                {
                    "node_type": node_type,
                    "ports": []
                }
            ]
        }

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": []}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name=node_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": green_port_name,
                                "parent_type": "node"
                            }
                         }, {
                            "kind": "port",
                            "data": {
                                "name": blue_port_name,
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name=green_port_name,
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            )
        ])

        expected_response = []

        response = FilterModule().import_nodes(data, client)

        self.assertEqual(response, expected_response)

    def test_mupltiple_nodes_with_ports_and_tags(self):
        node_type = "ovs-compute"
        tag_values = ["management-port", "other-tag", "some-tag"]
        data = {
            "nodes": [
                {
                    "name": "node-1",
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": "ens224",
                            "mac_address": "00:0c:29:13:37:aa",
                            "switch_name": "VM283DD71D00",
                            "fq_name": ['default-global-system-config',
                                        'node-1', 'ens224'],
                            "tags": tag_values[:2]
                        }
                    ]
                },
                {
                    "name": "node-2",
                    "node_type": node_type,
                    "ports": [
                        {
                            "name": "ens224",
                            "mac_address": "00:0c:29:13:37:bb",
                            "switch_name": "VM283DD71D22",
                            "fq_name": ['default-global-system-config',
                                        'node-2', 'ens224'],
                        },
                        {
                            "name": "ens227",
                            "mac_address": "00:0c:29:13:37:cc",
                            "switch_name": "VM283DD71D22",
                            "fq_name": ['default-global-system-config',
                                        'node-2', 'ens227'],
                            "tags": tag_values[2:]
                        }
                    ]
                },
                {
                    "name": "node-3",
                    "node_type": node_type
                }
            ]
        }
        client = FakeCCClient([
            GetAcceptRequest(
                res_type="node",
                response={"nodes": []}
            ),
            GetAcceptRequest(
                res_type="port",
                response={"ports": []}
            ),
            GetAcceptRequest(
                res_type="tag",
                response={"tags": [
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[0],
                            "name": '{}={}'.format("label", tag_values[0]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[0])],
                        }
                    },
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[1],
                            "name": '{}={}'.format("label", tag_values[1]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[1])],
                        }
                    },
                    {
                        "tag": {
                            "tag_type_name": "label",
                            "tag_value": tag_values[2],
                            "name": '{}={}'.format("label", tag_values[2]),
                            "fq_name": ['{}={}'.format("label",
                                                       tag_values[2])],
                        }
                    }
                ]}
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": "node-1",
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name="node-1",
                    uuid="beefbeef-beef-beef-beef-beefbeef1111"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": "node-2",
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name="node-2",
                    uuid="beefbeef-beef-beef-beef-beefbeef2222"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "node",
                            "data": {
                                "node_type": node_type,
                                "name": "node-3",
                                "parent_type": "global-system-config"
                            }
                         }]
                         },
                response=self.__get_node_create_response_content(
                    name="node-3",
                    uuid="beefbeef-beef-beef-beef-beefbeef3333"
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": 'ens224',
                                "fq_name": ['default-global-system-config',
                                            'node-1', 'ens224'],
                                "parent_type": "node"
                            }
                         }]
                         },
                response=self.__get_port_response_content(
                    name='ens224',
                    uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef1111",
                    fq_name=['default-global-system-config', 'node-1',
                             'ens224']
                )
            ),
            CreateAcceptRequest(
                payload={"resources":
                         [{
                            "kind": "port",
                            "data": {
                                "name": 'ens224',
                                "fq_name": ['default-global-system-config',
                                            'node-2', 'ens224'],
                                "parent_type": "node"
                            }
                         },
                            {
                                "kind": "port",
                                "data": {
                                    "name": 'ens227',
                                    "fq_name": ['default-global-system-config',
                                                'node-2', 'ens227'],
                                    "parent_type": "node"
                                }
                            }]
                         },
                response=self.__get_port_response_content(
                    name='ens224',
                    uuid="beefbeef-beef-beef-beef-beefbeef4444",
                    parent_uuid="beefbeef-beef-beef-beef-beefbeef2222",
                    fq_name=['default-global-system-config', 'node-2',
                             'ens224']
                )
            ),
        ])

        response = FilterModule().import_nodes(data, client)

        self.assertEqual(len(response), 3)

        client.assert_results()

    @staticmethod
    def __get_node_create_response_content(name, uuid):
        return [{
            "data": {
                "display_name": name,
                "fq_name": ["default-global-system-config", name],
                "name": name,
                "parent_type": "global-system-config",
                "parent_uuid": "beefbeef-beef-beef-beef-beefbeef0001",
                "uuid": uuid,
                "to": ["default-global-system-config", name]
            },
            "kind": "node",
            "operation": "CREATE"
        }]

    @staticmethod
    def __get_port_response_content(name, uuid, parent_uuid, fq_name=None):
        response = [{
            "data": {
                "display_name": name,
                "name": name,
                "uuid": uuid,
                "parent_type": "node",
                "parent_uuid": parent_uuid,
            },
            "kind": "port",
            "operation": "CREATE"
        }]
        if fq_name:
            response[0]['data']['fq_name'] = fq_name
        return response

    @staticmethod
    def __get_tag_response_content(value):
        name = "label={}".format(value)

        return [{
            "data": {
                "name": name,
                "fq_name": [name],
                "tag_type_name": "label",
                "tag_value": value,
            },
            "kind": "tag",
            "operation": "CREATE"
        }]
