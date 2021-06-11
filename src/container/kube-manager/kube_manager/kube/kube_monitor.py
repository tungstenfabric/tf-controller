#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#
from builtins import next
import json
import socket
import time
import requests

from six import StringIO

from cfgm_common.utils import cgitb_hook


class KubeMonitor(object):

    k8s_api_resources = {
        'pod': {
            'kind': 'Pod',
            'version': 'v1',
            'k8s_url_resource': 'pods',
            'group': ''},
        'service': {
            'kind': 'Service',
            'version': 'v1',
            'k8s_url_resource': 'services',
            'group': ''},
        'ingress': {
            'kind': 'Ingress',
            'version': 'v1beta1',
            'k8s_url_resource': 'ingresses',
            'group': 'extensions'},
        'endpoints': {
            'kind': 'Endpoints',
            'version': 'v1',
            'k8s_url_resource': 'endpoints',
            'group': ''},
        'namespace': {
            'kind': 'Namespace',
            'version': 'v1',
            'k8s_url_resource': 'namespaces',
            'group': ''},
        'networkpolicy': {
            'kind': 'NetworkPolicy',
            'version': 'v1',
            'k8s_url_resource': 'networkpolicies',
            'group': 'networking.k8s.io'},
        'customresourcedefinition': {
            'kind': 'CustomResourceDefinition',
            'version': 'v1beta1',
            'k8s_url_resource': 'customresourcedefinitions',
            'group': 'apiextensions.k8s.io'},
        'networkattachmentdefinition': {
            'kind': 'NetworkAttachmentDefinition',
            'version': 'v1',
            'k8s_url_resource': 'network-attachment-definitions',
            'group': 'k8s.cni.cncf.io'}
    }

    def __init__(self, args=None, logger=None, q=None, db=None,
                 resource_type='KubeMonitor', api_group=None, api_version=None):
        self.name = type(self).__name__
        self.args = args
        self.logger = logger
        self.q = q
        self.cloud_orchestrator = self.args.orchestrator
        # token valid only for OpenShift
        self.token = self.args.token
        self.headers = {'Connection': 'Keep-Alive'}
        self.verify = False
        self.timeout = 60

        # Per-monitor stream handle to api server.
        self.kube_api_resp = None
        self.kube_api_stream_handle = None

        # Use Kube DB if kube object caching is enabled in config.
        if args.kube_object_cache == 'True':
            self.db = db
        else:
            self.db = None

        self.kubernetes_api_server = self.args.kubernetes_api_server
        if self.token:
            protocol = "https"
            header = {'Authorization': "Bearer " + self.token}
            self.headers.update(header)
            self.verify = False
            self.kubernetes_api_server_port = \
                self.args.kubernetes_api_secure_port
        else:  # kubernetes
            protocol = "http"
            self.kubernetes_api_server_port = self.args.kubernetes_api_port

        self.url = "%s://%s:%s" % (protocol,
                                   self.kubernetes_api_server,
                                   self.kubernetes_api_server_port)

        if (resource_type == 'KubeMonitor'):
            # this is only for base class which instance is used as kube config
            self.base_url = self.url + "/openapi/v2"
            self._is_kube_api_server_alive(wait=True)
            resp = requests.get(
                self.base_url,
                headers=self.headers,
                verify=self.verify)
            try:
                resp.raise_for_status()
                json_data = resp.json()['definitions']
                for key in json_data.keys():
                    if 'x-kubernetes-group-version-kind' in json_data[key]:
                        k8s_resource = \
                            json_data[key]['x-kubernetes-group-version-kind'][0]
                        kind_lower = k8s_resource['kind'].lower()
                        if kind_lower in self.k8s_api_resources.keys():
                            self.k8s_api_resources[kind_lower]['version'] = \
                                k8s_resource['version']
                            self.k8s_api_resources[kind_lower]['kind'] = \
                                k8s_resource['kind']
                            self.k8s_api_resources[kind_lower]['group'] = \
                                k8s_resource['group']
            except Exception:
                raise
            finally:
                resp.close()

        # Resource Info corresponding to this monitor.
        self.resource_type = resource_type
        api_group, api_version, self.k8s_url_resource = \
            self._get_k8s_api_resource(resource_type, api_group, api_version)

        # Get the base kubernetes url to use for this resource.
        # Each resouce can be independently configured to use difference
        # versions or api groups. So we let the resource class specify what
        # version and api group it is interested in. The base_url is constructed
        # with the input from the derived class and does not change for the
        # course of the process.
        # URL to the api server.
        self.base_url = self._get_base_url(self.url, api_group, api_version)
        self.logger.info("%s - KubeMonitor init done: url=%s" % (self.name, self.base_url))

    def _is_kube_api_server_alive(self, wait=False):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        while True:
            msg = "Connect Kube API %s:%s" % (self.kubernetes_api_server, self.kubernetes_api_server_port)
            self.logger.info("%s - %s" % (self.name, msg))
            try:
                # it cann raise errors related to host name resolving
                result = sock.connect_ex((self.kubernetes_api_server,
                                          int(self.kubernetes_api_server_port)))
            except (OSError, socket.error) as e:
                result = e.errno if e.errno else -1
            msg = "Connect Kube API result %s" % (result)
            self.logger.debug("%s - %s" % (self.name, msg))
            if wait and result != 0:
                # Connect to Kubernetes API server was not successful.
                # If requested, wait indefinitely till connection is up.
                msg = "kube_api_service is not reachable. Retry in %s secs." % (self.timeout)
                self.logger.error("%s - %s" % (self.name, msg))
                time.sleep(self.timeout)
                continue

            # Return result of connection attempt to kubernetes api server.
            return result == 0

    def _get_k8s_api_resource(self, resource_type, api_group, api_version):
        if resource_type in self.k8s_api_resources:
            api_version = \
                self.k8s_api_resources[resource_type]['version']
            if self.k8s_api_resources[resource_type]['group'] != '':
                api_group = \
                    'apis/' + self.k8s_api_resources[resource_type]['group']
            else:
                api_group = ''
            k8s_url_resource = \
                self.k8s_api_resources[resource_type]['k8s_url_resource']
        else:
            k8s_url_resource = resource_type
        return api_group, api_version, k8s_url_resource

    @classmethod
    def _get_base_url(cls, url, api_group, api_version):
        ''' Construct a base url. '''
        version = api_version if api_version else "v1"
        group = api_group if api_group else "api"

        # URL to the v1-components in api server.
        url = "/".join([url, group, version])

        return url

    def get_component_url(self):
        """URL to a component.
        This method return the URL for the component represented by this
        monitor instance.
        """
        return "%s/%s" % (self.base_url, self.k8s_url_resource)

    def get_entry_url(self, entry):
        """URL to an entry of this component.
        This method returns a URL to a specific entry of this component.
        """
        namespace = entry['metadata'].get('namespace')
        url_namespace = ("/namespaces/" + namespace) if namespace else ""
        return "%s%s/%s/%s" % (self.base_url, url_namespace,
                               self.k8s_url_resource, entry['metadata']['name'])

    def init_monitor(self):
        """Initialize/sync a monitor component.
        This method will initialize a monitor component.
        As a part of this init, this method will read existing entries in api
        server and populate the local db.
        """
        url = self.get_component_url()
        self.logger.info("%s - Start init_monitor component_url=%s" % (self.name, url))

        # Check if kubernetes api service is up. If not, wait till its up.
        self._is_kube_api_server_alive(wait=True)

        # Get the URL to this component.
        resp = requests.get(url, headers=self.headers, verify=self.verify)
        try:
            resp.raise_for_status()
            initial_entries = resp.json()['items']
        except Exception:
            raise
        finally:
            resp.close()
        for entry in initial_entries:
            entry_url = self.get_entry_url(entry)
            resp = requests.get(entry_url, headers=self.headers,
                                verify=self.verify)
            try:
                resp.raise_for_status()
                # Construct the event and initiate processing.
                event = {'object': resp.json(), 'type': 'ADDED'}
                self.process_event(event)
            except Exception:
                raise
            finally:
                resp.close()
        self.logger.info("%s - Done init_monitor component_url=%s" % (self.name, url))

    def register_monitor(self):
        """Register this component for notifications from api server.
        """
        if self.kube_api_resp:
            self.kube_api_resp.close()

        # Check if kubernetes api service is up. If not, wait till its up.
        self._is_kube_api_server_alive(wait=True)

        url = self.get_component_url()
        self.logger.info("%s - Start Watching request %s" % (self.name, url))
        resp = requests.get(url, params={'watch': 'true'},
                            stream=True, headers=self.headers,
                            verify=self.verify)
        try:
            resp.raise_for_status()
        except Exception:
            resp.close()
            raise
        # Get handle to events for this monitor.
        self.kube_api_resp = resp
        self.kube_api_stream_handle = resp.iter_lines(chunk_size=256, delimiter='\n')
        self.logger.info("%s - Watches %s" % (self.name, url))

    def get_resource(self, resource_type, resource_name,
                     namespace=None, api_group=None, api_version=None):
        json_data = {}
        api_group, api_version, k8s_url_resource = \
            self._get_k8s_api_resource(resource_type, api_group, api_version)

        base_url = self._get_base_url(self.url, api_group, api_version)
        if resource_type == "namespace":
            url = "%s/%s" % (base_url, k8s_url_resource)
        elif resource_type == "customresourcedefinition":
            url = "%s/%s/%s" % (base_url, k8s_url_resource, resource_name)
        else:
            url = "%s/namespaces/%s/%s/%s" % (base_url, namespace,
                                              k8s_url_resource, resource_name)

        try:
            resp = requests.get(url, stream=True,
                                headers=self.headers, verify=self.verify)
            if resp.status_code == 200:
                json_data = json.loads(resp.raw.read())
            resp.close()
        except (OSError, IOError, socket.error) as e:
            self.logger.error("%s - %s" % (self.name, e))

        return json_data

    def patch_resource(
            self, resource_type, resource_name,
            merge_patch, namespace=None, sub_resource_name=None,
            api_group=None, api_version=None):
        api_group, api_version, k8s_url_resource = \
            self._get_k8s_api_resource(resource_type, api_group, api_version)

        base_url = self._get_base_url(self.url, api_group, api_version)
        if resource_type == "namespace":
            url = "%s/%s" % (base_url, k8s_url_resource)
        else:
            url = "%s/namespaces/%s/%s/%s" % (base_url, namespace,
                                              k8s_url_resource, resource_name)
            if sub_resource_name:
                url = "%s/%s" % (url, sub_resource_name)

        headers = {'Accept': 'application/json',
                   'Content-Type': 'application/strategic-merge-patch+json'}
        headers.update(self.headers)

        try:
            resp = requests.patch(url, headers=headers,
                                  data=json.dumps(merge_patch),
                                  verify=self.verify)
            if resp.status_code != 200:
                resp.close()
                return
        except (OSError, IOError, socket.error) as e:
            self.logger.error("%s - %s" % (self.name, e))
            return

        return resp.iter_lines(chunk_size=10, delimiter='\n')

    def post_resource(self, resource_type, resource_name,
                      body_params, namespace=None, sub_resource_name=None,
                      api_group=None, api_version=None):
        api_group, api_version, k8s_url_resource = \
            self._get_k8s_api_resource(resource_type, api_group, api_version)

        base_url = self._get_base_url(self.url, api_group, api_version)
        if resource_type in ("namespace", "customresourcedefinition"):
            url = "%s/%s" % (base_url, k8s_url_resource)
        else:
            url = "%s/namespaces/%s/%s/%s" % (base_url, namespace,
                                              k8s_url_resource, resource_name)
            if sub_resource_name:
                url = "%s/%s" % (url, sub_resource_name)

        headers = {'Accept': 'application/json',
                   'Content-Type': 'application/json',
                   'Authorization': "Bearer " + self.token}
        headers.update(self.headers)

        try:
            resp = requests.post(url, headers=headers,
                                 data=json.dumps(body_params),
                                 verify=self.verify)
            if resp.status_code not in [200, 201]:
                resp.close()
                return None
        except (OSError, IOError, socket.error) as e:
            self.logger.error("%s - %s" % (self.name, e))
            return None

        return resp.iter_lines(chunk_size=10, delimiter='\n')

    def process(self):
        """Process available events."""
        try:
            self.logger.info("%s - start process kube event" % (self.name))

            if not self.kube_api_stream_handle or \
               not self.kube_api_resp or \
               not self.kube_api_resp.raw._fp.fp:

                self.logger.error(
                    "%s - Event handler not found. "
                    "Re-registering event handler" % self.name)
                self.register_monitor()

            line = next(self.kube_api_stream_handle)
            if line:
                self.process_event(json.loads(line))
        except StopIteration:
            pass
        except (OSError, IOError, socket.error,
                requests.exceptions.ChunkedEncodingError) as e:
            self.logger.error("%s - %s" % (self.name, e))
        except ValueError:
            self.logger.error(
                "Invalid JSON data from response stream:%s" % line)
        except Exception as e:
            string_buf = StringIO()
            cgitb_hook(file=string_buf, format="text")
            err_msg = string_buf.getvalue()
            self.logger.error("%s - %s - %s" % (self.name, e, err_msg))

    def event_callback(self):
        while True:
            self.process()
            time.sleep(0)

    def process_event(self, event):
        """Process an event."""
        pass
