#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#
from builtins import next
import json
import requests
import socket
import time
import sys

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
        self.headers = {
            'Connection': 'Keep-Alive',
            'Accept': 'application/json; charset="UTF-8"'
        }
        self.verify = False

        self.timeout = int(self.args.kube_timer_interval) if self.args.kube_timer_interval else None
        self.resource_version = None
        self.resource_version_valid = False
        if not self.verify:
            # disable ssl insecure warning
            requests.packages.urllib3.disable_warnings()

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
        self.kind = self.k8s_api_resources.get(self.resource_type, {}).get('kind')

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
        self._log("%s - KubeMonitor init done: url=%s" % (self.name, self.base_url))

    def _is_kube_api_server_alive(self, wait=False):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        while True:
            msg = "Try to connect Kube API %s:%s" % \
                  (self.kubernetes_api_server, self.kubernetes_api_server_port)
            self._log("%s - %s" % (self.name, msg))
            try:
                # it cann raise errors related to host name resolving
                result = sock.connect_ex((self.kubernetes_api_server,
                                          int(self.kubernetes_api_server_port)))
            except (OSError, socket.error) as e:
                result = e.errno if e.errno else -1
            msg = "Connect Kube API result %s" % (result)
            self._log("%s - %s" % (self.name, msg))
            if wait and result != 0:
                # Connect to Kubernetes API server was not successful.
                # If requested, wait indefinitely till connection is up.
                msg = "kube_api_service is not reachable. Retry in 10 secs."
                self._log("%s - %s" % (self.name, msg), level='error')
                time.sleep(10)
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
        self._log("%s - Start init url=%s resource_version=%s"
                  % (self.name, url, self.resource_version))

        resource_version = self.resource_version
        params = None
        if resource_version:
            params = {"resourceVersion": resource_version}
        resp = requests.get(url, headers=self.headers, verify=self.verify, params=params)
        try:
            resp.raise_for_status()
            jdata = resp.json()
            initial_entries = jdata['items']
            resource_version = jdata.get('metadata', {}).get('resourceVersion')
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
        self.resource_version = resource_version
        self.resource_version_valid = bool(self.resource_version)
        self._log("%s - Done init url=%s, resource_version=%s"
                  % (self.name, url, self.resource_version))

    def register_monitor(self):
        """Register this component for notifications from api server.
        """
        if not self.resource_version_valid:
            self.resource_version = None

        if self.kube_api_resp:
            self.kube_api_resp.close()

        # Check if kubernetes api service is up. If not, wait till its up.
        self._is_kube_api_server_alive(wait=True)

        # init monitor and assign resourceVersion
        if not self.resource_version:
            self.init_monitor()

        # schedule tasks for cleanups after all objects read from kube
        # and before to read new objects from kube
        # (this sync update PODs that were created before node is up (vrouter is registered))
        self._schedule_vnc_sync()

        url = self.get_component_url()
        params = {
            'watch': 'true',
            'allowWatchBookmarks': 'true',
            "resourceVersion": self.resource_version
        }
        self._log(
            "%s - Start Watching request %s (%s)(timeout=%s)"
            % (self.name, url, params, self.timeout))
        resp = requests.get(url, params=params,
                            stream=True, headers=self.headers,
                            verify=self.verify,
                            timeout=self.timeout)
        try:
            resp.raise_for_status()
        except Exception:
            resp.close()
            raise
        # Get handle to events for this monitor.
        self.kube_api_resp = resp
        self.kube_api_stream_handle = resp.iter_lines(chunk_size=256, delimiter='\n')
        self._log("%s - Watches %s (%s)" % (self.name, url, params))

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
            self._log("%s - %s" % (self.name, e), level='error')

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
            self._log("%s - %s" % (self.name, e), level='error')
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
            self._log("%s - %s" % (self.name, e), level='error')
            return None

        return resp.iter_lines(chunk_size=10, delimiter='\n')

    def _schedule_vnc_sync(self):
        self._log("%s - _schedule_vnc_sync: schedule" % (self.name))
        # artificial internal event to sync objects periodically
        self.q.put(({'type': 'TF_VNC_SYNC', "object": {"kind": self.kind}}, None))

    def process(self):
        """Process available events."""
        try:
            self._log("%s - start process kube event" % (self.name))

            if not self.resource_version_valid or \
               not self.kube_api_stream_handle or \
               not self.kube_api_resp or \
               not self.kube_api_resp.raw._fp.fp:

                msg = "%s - Re-registering event handler. " \
                      "resource_version_valid=%s, resource_version=%s" \
                      % (self.name, self.resource_version_valid, self.resource_version)
                self._log(msg)
                self.register_monitor()

            line = next(self.kube_api_stream_handle)
            if line:
                self._process_event(json.loads(line))
        except StopIteration:
            pass
        except requests.HTTPError as e:
            if e.response.status_code == 410:
                # means "Gone response from kube api"
                # and requires to re-request resources w/o resourceVersion set
                self._log("%s - invalidate resourceVersion %s (response 410)"
                          % (self.name, self.resource_version), level='error')
                self.resource_version_valid = False
        except (OSError, IOError, socket.error,
                requests.exceptions.ChunkedEncodingError) as e:
            self._log("%s - %s" % (self.name, e), level='error')
        except ValueError:
            self._log("Invalid JSON data from response stream:%s" % line, level='error')
        except Exception as e:
            string_buf = StringIO()
            cgitb_hook(file=string_buf, format="text")
            err_msg = string_buf.getvalue()
            self._log("%s - %s - %s" % (self.name, e, err_msg), level='error')

    def event_callback(self):
        while True:
            self.process()
            time.sleep(0)

    def _log(self, msg, level='info'):
        print(msg)
        if level == 'error':
            self.logger.error(msg)
        else:
            self.logger.info(msg)

    def _process_event(self, event):
        event_type = event['type']
        obj = event['object']
        kind = obj.get('kind')
        metadata = obj['metadata']
        namespace = metadata.get('namespace')
        name = metadata.get('name')
        uid = metadata.get('uid')

        if event_type == 'ERROR':
            # {'object': {
            #     'status': 'Failure', 'kind': 'Status', 'code': 410,
            #     'apiVersion': 'v1', 'reason': 'Expired',
            #     'message': 'too old resource version: 6384 (12181)', 'metadata': {}
            #   },
            #  'type': u'ERROR'}
            msg = "%s - Received ERROR: %s" % (self.name, event)
            if kind == 'Status' and obj.get('code') == 410:
                msg += " - invalidate resourceVersion (%s)" % (self.resource_version)
                self._log(msg, level='error')
                self.resource_version_valid = False
            else:
                self._log(msg, level='error')
            return

        if event_type == 'BOOKMARK':
            # update resource version for next watch call, e.g.
            # {
            #   "type": "BOOKMARK",
            #   "object": {"kind": "Pod", "apiVersion": "v1", "metadata": {"resourceVersion": "12746"} }
            # }
            if self.kind and self.kind != kind:
                self._log("%s - Received BOOKMARK: Internal error: received %s for %s Monitor" %
                          (self.name, kind, self.kind), level='error')
                # Wrong behaviour - internal program error
                sys.exit(1)
            new_version = metadata['resourceVersion']
            self._log("%s - Received BOOKMARK: oldResVer=%s newResVer=%s" %
                      (self.name, self.resource_version, new_version))
            self.resource_version = new_version
            return

        msg_obj = "%s %s %s:%s:%s" \
                  % (event_type, kind, namespace, name, uid)
        if self.kind and self.kind != kind:
            self._log("%s - Internal error: Received %s for %s Monitor" %
                      (self.name, msg_obj, self.kind), level='error')
            # Wrong behaviour - internal program error
            sys.exit(1)
        self._log("%s - Received %s" % (self.name, msg_obj))

        self.process_event(event)

    def register_event(self, uuid, event):
        data = event['object']
        event_type = event['type']
        metadata = data.get('metadata', {})

        kind = data.get('kind')
        namespace = metadata.get('namespace')
        name = metadata.get('name')

        msg = "%s - Got %s %s %s:%s:%s" \
              % (self.name, event_type, kind, namespace, name, uuid)
        print(msg)
        self.logger.debug(msg)
        self.q.put((event, self.event_process_callback))

    def event_process_callback(self, event, err):
        if err is not None:
            msg = "%s - invalidate resourceVersion (%s): Vnc event process error: %s (%s)" \
                  % (self.name, self.resource_version, err, event)
            self._log(msg, level='error')
            # invalidate resourceVersion as something went wrong
            # and it is needed to check data consistency
            # on next cycle
            self.resource_version_valid = False

    def process_event(self, event):
        """Process an event."""
        pass
