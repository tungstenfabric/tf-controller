from assert_dictionaries import assert_subset_dictionaries


_RESOURCES_KEY = "resources"


class CreateAcceptRequest:
    def __init__(
            self,
            payload,
            throw_http_error=False,
            response=None
    ):
        self.payload = payload
        self.throw_http_error = throw_http_error
        self.response = response

    def __str__(self):
        return """Payload: '{}'
            Command Response Code: '{}'
            Command Response Content: '{}'
            """.format(
                self.payload,
                self.throw_http_error,
                self.response
            )


class GetAcceptRequest:
    def __init__(
            self,
            res_type,
            throw_http_error=False,
            response=None
    ):
        self.resource_type = res_type
        self.throw_http_error = throw_http_error
        self.response = response

    def __str__(self):
        return """Resource Type: '{}'
            Command Response Code: '{}'
            Command Response Content: '{}'
            """.format(
                self.resource_type,
                self.throw_http_error,
                self.response
            )


class FakeCCClient:
    """Fake Contrail Command Client.

    This Client allows user to specify the list of expected requests.
    For creating/getting resources method the client will look up for
    the specified kind and name within list of accepted requests.
    The workflow looks like this:

        1. CC Client's Create resource function is called.
        2. Resource name and kind are extracted from input payload.
        3. CC Client reads the payload/kind argument and finds first matching
           payload/kind from the AcceptRequest list. If it won't find any
           matching request it will raise an exception.
        4. CC Client returns specified response that corresponds with
           previously found request.
        5. CC Client removes previously found request from the accept list.

    At the end of the test an accept_requests list should be empty.
    Otherwise test will raise an error as not all requests appeared.
    """

    def __init__(self, accept_requests):
        if accept_requests is None:
            accept_requests = []
        self.__validate(accept_requests)
        self.__accept_requests = accept_requests

    def __validate(self, accept_requests):
        if not isinstance(accept_requests, list):
            raise self.InvalidTestConfigurationException(
                "accept request parameter is not a list")

        for ar in accept_requests:
            if not (isinstance(ar, CreateAcceptRequest)
                    or isinstance(ar, GetAcceptRequest)):
                raise self.InvalidTestConfigurationException(
                    "accept request list contains invalid objects")

    def create_cc_resource(self, res_request_payload):
        self.__validate_request_payload(res_request_payload)

        for i, r in enumerate(self.__accept_requests):
            if not isinstance(r, CreateAcceptRequest):
                continue

            if not assert_subset_dictionaries(r.payload, res_request_payload):
                continue

            self.__accept_requests.pop(i)

            if r.throw_http_error:
                raise self.HTTPError

            return r.response

        raise self.UnhandledCreateRequestException(
            "Missing Accept Request matching payload '{}'".format(
                res_request_payload
            )
        )

    def __validate_request_payload(self, request_payload):
        if not isinstance(request_payload, dict):
            raise self.InvalidPayloadFormException(
                "Request payload is not a dict"
            )
        if _RESOURCES_KEY not in request_payload:
            raise self.InvalidPayloadFormException(
                "Expected dict with '{}' key. Got '{}'".format(
                    _RESOURCES_KEY, request_payload
                )
            )
        resources = request_payload[_RESOURCES_KEY]
        if resources is None:
            raise self.InvalidPayloadFormException(
                "Empty value for '{}' key".format(_RESOURCES_KEY)
            )
        if not isinstance(resources, list):
            raise self.InvalidPayloadFormException(
                "Expected list value for '{}' key. Got: '{}'".format(
                    _RESOURCES_KEY, resources
                )
            )

    def list_cc_resources(self, kind):
        for i, r in enumerate(self.__accept_requests):
            if (not isinstance(r, GetAcceptRequest)) \
                    or r.resource_type != kind:
                continue

            self.__accept_requests.pop(i)

            if r.throw_http_error:
                raise self.HTTPError

            return r.response

        raise self.UnhandledGetRequestException(kind)

    def assert_results(self):
        if len(self.__accept_requests) == 0:
            return
        raise self.MissingFunctionCallsException(
            ''.join(["Missing {} function calls: ".format(len(
                self.__accept_requests))]
                    + [str(i) for i in self.__accept_requests])
        )

    class HTTPError(Exception):
        pass

    class InvalidTestConfigurationException(Exception):
        pass

    class InvalidPayloadFormException(Exception):
        pass

    class UnhandledCreateRequestException(Exception):
        pass

    class UnhandledGetRequestException(Exception):
        pass

    class MissingFunctionCallsException(Exception):
        pass
