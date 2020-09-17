import unittest

from fake_cc_client import FakeCCClient, CreateAcceptRequest, GetAcceptRequest

def prepare_create_payload(kind, name):
    return {
        "resources": [
            {
                "kind": kind,
                "data": {
                    "name": name
                }
            }
        ]
    }

class TestFakeCClient(unittest.TestCase):
    def test_constructor_with_none_argument(self):
        FakeCCClient(None)

    def test_constructor_with_invalid_argument(self):
        self.assertRaises(
            FakeCCClient.InvalidTestConfigurationException,
            FakeCCClient, {}
        )

    def test_constructor_with_empty_list(self):
        FakeCCClient([])

    def test_constructor_with_list_containing_invalid_argument(self):
        self.assertRaises(
            FakeCCClient.InvalidTestConfigurationException,
            FakeCCClient, [{}]
        )

    def test_constructor_with_create_accept_request(self):
        FakeCCClient(
            [
                CreateAcceptRequest("{}", False)
            ]
        )

    def test_constructor_with_get_accept_request(self):
        FakeCCClient(
            [
                GetAcceptRequest("node", False)
            ]
        )

    def test_create_without_accept_requests(self):
        client = FakeCCClient(None)
        self.assertRaises(
            FakeCCClient.UnhandledCreateRequestException,
            client.create_cc_resource, prepare_create_payload("node", "nodeX")
        )

    def test_get_without_accept_requests(self):
        client = FakeCCClient(None)
        self.assertRaises(
            FakeCCClient.UnhandledGetRequestException,
            client.get_cc_resource, "node"
        )

    def test_create_with_non_matching_payload(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeY")
            )
        ])
        self.assertRaises(
            FakeCCClient.UnhandledCreateRequestException,
            client.create_cc_resource, prepare_create_payload("node", "nodeX")
        )

    def test_get_with_unequal_resource_type(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port")
        ])
        self.assertRaises(
            FakeCCClient.UnhandledGetRequestException,
            client.get_cc_resource, "node"
        )

    def test_create_with_proper_request(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            )
        ])
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))

    def test_get_with_proper_request(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port")
        ])
        client.list_cc_resources("port")

    def test_create_twice_with_single_expected_request(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            )
        ])
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))
        self.assertRaises(
            FakeCCClient.UnhandledCreateRequestException,
            client.create_cc_resource, prepare_create_payload("node", "nodeX")
        )

    def test_get_twice_with_single_expected_request(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port")
        ])
        client.list_cc_resources("port")
        self.assertRaises(
            FakeCCClient.UnhandledGetRequestException,
            client.get_cc_resource, "port"
        )

    def test_create_twice(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            ),
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            )
        ])
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))

    def test_get_twice(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port"),
            GetAcceptRequest(res_type="port")
        ])
        client.list_cc_resources("port")
        client.list_cc_resources("port")

    def test_two_different_creates(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            ),
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeY")
            )
        ])
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))
        client.create_cc_resource(prepare_create_payload("node", "nodeY"))

    def test_two_different_gets(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port"),
            GetAcceptRequest(res_type="node")
        ])
        client.list_cc_resources("port")
        client.list_cc_resources("node")

    def test_two_different_creates_in_different_order(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            ),
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeY")
            )
        ])
        client.create_cc_resource(prepare_create_payload("node", "nodeY"))
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))

    def test_two_different_gets_in_different_order(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port"),
            GetAcceptRequest(res_type="node")
        ])
        client.list_cc_resources("node")
        client.list_cc_resources("port")

    def test_get_with_create_accept_request(self):
        client = FakeCCClient([
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeY")
            )
        ])
        self.assertRaises(
            FakeCCClient.UnhandledGetRequestException,
            client.get_cc_resource, "node"
        )

    def test_create_with_get_accept_request(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="node")
        ])
        self.assertRaises(
            FakeCCClient.UnhandledCreateRequestException,
            client.create_cc_resource, prepare_create_payload("node", "nodeX")
        )

    def test_get_and_create(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="node"),
            CreateAcceptRequest(
                payload=prepare_create_payload("node", "nodeX")
            )
        ])
        client.list_cc_resources("node")
        client.create_cc_resource(prepare_create_payload("node", "nodeX"))

    def test_assert_results(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port"),
            GetAcceptRequest(res_type="node")
        ])
        client.list_cc_resources("node")
        client.list_cc_resources("port")
        client.assert_results()

    def test_assert_results_with_missing_request(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port"),
            GetAcceptRequest(res_type="node")
        ])
        client.list_cc_resources("node")
        self.assertRaises(
            FakeCCClient.MissingFunctionCallsException,
            client.assert_results
        )

    def test_http_error(self):
        client = FakeCCClient([
            GetAcceptRequest(res_type="port", throw_http_error=True)
        ])
        self.assertRaises(
            FakeCCClient.HTTPError,
            client.get_cc_resource, "port"
        )

    def test_response(self):
        expected_response = "test123"
        client = FakeCCClient([
            GetAcceptRequest(
                res_type="port",
                response=expected_response
            )
        ])
        response = client.list_cc_resources("port")
        self.assertEqual(response, expected_response)

    def test_response_order(self):
        expected_response_a = "test123"
        expected_response_b = "test456"

        client = FakeCCClient([
            GetAcceptRequest(
                res_type="port",
                response=expected_response_a
            ),
            GetAcceptRequest(
                res_type="port",
                response=expected_response_b
            )
        ])
        response_a = client.list_cc_resources("port")
        self.assertEqual(response_a, expected_response_a)

        response_b = client.list_cc_resources("port")
        self.assertEqual(response_b, expected_response_b)



