from __future__ import absolute_import
from future import standard_library
standard_library.install_aliases()
from builtins import object
from six.moves import configparser
import logging
import exceptions
import requests
import json
import base64
from .tls import TLS


class CloudstackCertManager(object):

    def __init__(self, auth_conf=None):
        if auth_conf:
            self.auth_conf = auth_conf
        else:
            self.auth_conf = '/etc/contrail/contrail-lbaas-auth.conf'
        self.parse_args()

        self.headers = {'Connection': 'Keep-Alive'}
        self.verify = False
        self.baseurl = "%s://%s:%s/%s/api" % (self.cloudstack_api_protocol,
                                              self.cloudstack_api_server,
                                              self.cloudstack_api_port,
                                              self.cloudstack_api_context)

    def parse_args(self):
        config = configparser.SafeConfigParser()
        config.read(self.auth_conf)

        self.cloudstack_api_protocol = config.get('CLOUDSTACK',
                                                  'cloudstack_api_protocol')
        self.cloudstack_api_server = config.get('CLOUDSTACK',
                                                'cloudstack_api_server')
        self.cloudstack_api_port = config.get('CLOUDSTACK',
                                              'cloudstack_api_port')
        self.cloudstack_api_context = config.get('CLOUDSTACK',
                                                 'cloudstack_api_context')

    def get_resource(self, params):
        json_data = {}
        url = "%s?%s" % (self.baseurl, params)
        try:
            resp = requests.get(url, stream=True, headers=self.headers,
                                verify=self.verify)
            if resp.status_code == 200:
                json_data = json.loads(resp.content)
            resp.close()
        except requests.exceptions.RequestException as e:
            msg = "Error in getting data from cloudstack : %s" % e
            logging.exception(msg)

        return json_data

    def get_tls_certificates(self, params):
        try:
            json = self.get_resource(params)
            data = json['getloadbalancersslcertificateresponse']['data']
        except exceptions.Exception as e:
            msg = "Error in getting data from %s as %s" % (params, e)
            logging.exception(msg)
            return None
        certificate = base64.b64decode(data['crt'])
        private_key = base64.b64decode(data['key'])
        intermediates = base64.b64decode(data['chain'])
        primary_cn = TLS.get_primary_cn(certificate)
        return TLS(
            primary_cn=primary_cn,
            private_key=private_key,
            certificate=certificate,
            intermediates=intermediates)

    def update_ssl_config(self, haproxy_config, dest_dir):
        updated_config = haproxy_config
        for line in haproxy_config.split('\n'):
            if 'ssl crt' in line:
                try:
                    items = [x for x in line.split(' ')
                             if x.startswith('crt__')]
                except IndexError:
                    return None
                for item in items or []:
                    url = item[5:]
                    tls = self.get_tls_certificates(url)
                    if tls is None:
                        return None
                    pem_file_name = tls.create_pem_file(dest_dir)
                    if pem_file_name is None:
                        return None
                    updated_config =\
                        updated_config.replace(item, 'crt ' + pem_file_name)

        return updated_config
