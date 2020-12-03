from vnc_api import vnc_api
from netaddr import IPNetwork, IPAddress
import logging
import argparse
import calendar
import yaml
import time
import json
import sys
import os
import base64
import uuid
try:
    from six.moves.configparser import SafeConfigParser
except ImportError:
    from ConfigParser import SafeConfigParser

tenant_fqname = ['default-domain', 'default-project']

class ProvisionInfraNetwork(object):
    def __init__(self, args=''):
        """Pass the arguments given by command line."""
        self._args = args
        self.initialize_logger()
        self.get_vnc_h()
        self.read_yaml_file()
        self.vn_objs = dict()
        self.vlans = dict()

    def initialize_logger(self):
        self.logger = logging.getLogger(__name__)
        log_level = 'DEBUG' if self._args.debug else 'INFO'
        self.logger.setLevel(log_level)
        logformat = logging.Formatter("%(levelname)s: %(message)s")
        stdout = logging.StreamHandler(sys.stdout)
        stdout.setFormatter(logformat)
        self.logger.addHandler(stdout)
        logfile = logging.handlers.RotatingFileHandler(
            self._args.log_file, maxBytes=10000000, backupCount=5)
        logfile.setFormatter(logformat)
        self.logger.addHandler(logfile)

    def get_vnc_h(self):
        _api_args = ['api_server_host', 'domain_name',
                     'password', 'tenant_name', 'username']
        vnc_api_args = {
            k: getattr(self._args, k) for k in _api_args
            if getattr(self._args, k)
        }
        self.vnc = vnc_api.VncApi(**vnc_api_args)

    def read_yaml_file(self):
        with open(self._args.connections, 'r') as fd:
            self.connections = yaml.load(fd)

    def validate(self):
        networks = set()
        servers = set()
        physical_interfaces = set()
        vlans = set()
        self.logger.info('Validating the input yaml file')
        self.read_fabric(self._args.fabric)
        for network, details in self.connections.items():
            if network in networks:
                msg = 'Network %s is mentioned more than once'%network
                raise Exception(msg)
            networks.add(network)
            if IPAddress(details['gateway']) not in IPNetwork(details['cidr']):
                msg = 'Gateway {0} not in range of {1}'.format(
                    details['gateway'], details['cidr'])
                raise Exception(msg)
            if details['vlan'] in vlans:
                msg = 'Vlan %s is mentioned more than once'%details['vlan']
                raise Exception(msg)
            vlans.add(details['vlan'])
            for server, routers in details['servers'].items():
                servers.add(server)
                for router, pifs in routers.items():
                    for pif in pifs:
                        physical_interface = ":".join([router, pif])
                        self.read_physical_interface(physical_interface)
                        physical_interfaces.add(physical_interface)

    def create(self):
        self.logger.info('Creating requested connections')
        for network, details in self.connections.items():
            prouters = set()
            if 'data' in details and details['data']:
                data_network = True
            else:
                data_network = False
            self.check_and_create_network(network, details['cidr'],
                details['gateway'], details['vlan'])
            for server, routers in details['servers'].items():
                physical_interfaces = set()
                for router, pifs in routers.items():
                    for pif in pifs:
                        physical_interface = ":".join([router, pif])
                        physical_interfaces.add(physical_interface)
                    prouters.add(router)
                self.check_and_create_vpg(server, physical_interfaces, network, data_network, details.get('native_vlan'))
            self.extend_network_to_routers(network, routers)

    def read_fabric(self, name):
        fq_name = ['default-global-system-config', name]
        self.logger.debug('Reading Fabric %s'%name)
        return self.vnc.fabric_read(fq_name=fq_name)

    def read_router(self, name):
        fq_name = ['default-global-system-config', name]
        self.logger.debug('Reading physical router %s'%name)
        return self.vnc.physical_router_read(fq_name=fq_name)

    def read_physical_interface(self, physical_interface):
        fq_name = ['default-global-system-config'] + \
            physical_interface.split(':')
        self.logger.debug('Reading physical interface %s'%physical_interface)
        return self.vnc.physical_interface_read(fq_name=fq_name)

    def check_and_create_network(self, name, cidr, gateway, vlan):
        fq_name = tenant_fqname + [name]
        vn_obj = vnc_api.VirtualNetwork(name,
            parent_type='project',
            fq_name=fq_name)
        subnet, mask = cidr.split('/')
        ipam_attr = vnc_api.IpamSubnetType(
            subnet=vnc_api.SubnetType(subnet, mask),
            default_gateway=gateway)
        vn_obj.add_network_ipam(vnc_api.NetworkIpam(),
            vnc_api.VnSubnetsType([ipam_attr]))
        vn_properties = vnc_api.VirtualNetworkType()
        vn_properties.set_vxlan_network_identifier(int(vlan))
        vn_obj.set_virtual_network_properties(vn_properties)
        vn_obj.set_virtual_network_category('infra')
        try:
            self.vnc.virtual_network_create(vn_obj)
            self.logger.info('Created network %s'%name)
            self.vn_objs[name] = vn_obj
        except vnc_api.RefsExistError:
            self.vn_objs[name] = self.vnc.virtual_network_read(fq_name=fq_name)
        self.vlans[name] = vlan

    def make_uuid(self, name):
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, str(name)))

    def check_and_create_vpg(self, server, pifs, network, data_network, native_vlan=False):
        for pif in pifs:
            if not data_network:
                vpg_name = 'vpg#'+base64.b64encode(server)+base64.b64encode(pif.split(":")[0])
            elif data_network:
                vpg_name = 'vpg#'+base64.b64encode(server)
            self.logger.info('Creating VPG %s' %vpg_name)
            vpg_uuid = self.make_uuid(vpg_name)
            fq_name = ['default-global-system-config',
                   self._args.fabric, vpg_name]
            obj = vnc_api.VirtualPortGroup(server,
                fq_name=fq_name,
                parent_type='fabric')
            obj.uuid = vpg_uuid
            try:
                self.vnc.virtual_port_group_create(obj)
                self.logger.info('Created port group %s'%server)
            except vnc_api.RefsExistError:
                self.logger.debug('Reading port group %s'%server)
                obj = self.vnc.virtual_port_group_read(fq_name=fq_name)
            pif_obj = self.read_physical_interface(pif)
            obj.add_physical_interface(pif_obj)
            self.vnc.virtual_port_group_update(obj)
            self.logger.debug('Added interfaces %s to port group %s'%(
                pifs, server))
            port_name = vpg_name+pif.split(":")[1]+str(self.vlans[network])
            port_name = port_name.replace(':', '_')
            self.create_port(port_name, network, vpg_name, pifs, native_vlan)

    def create_port(self, name, network, vpg_name, pifs, native_vlan=False):
        fq_name = tenant_fqname + [name]
        try:
            port_obj = self.vnc.virtual_machine_interface_read(fq_name=fq_name)
        except vnc_api.NoIdError:
            port_obj = vnc_api.VirtualMachineInterface(name,
                fq_name=fq_name, parent_type='project')
        self.logger.info('Creating Port %s' %port_obj.fq_name)
        port_obj.add_virtual_network(self.vn_objs[network])
        device_owner = 'baremetal:None'
        interfaces = list()
        for pif in pifs:
            prouter, port = pif.split(':')
            interfaces.append({'switch_info': prouter,
                               'port_id': port, 'fabric': self._args.fabric})
        ll_info = {'local_link_information': interfaces}
        vlan = self.vlans[network]
        vmi_props = vnc_api.VirtualMachineInterfacePropertiesType()
        vmi_props.set_sub_interface_vlan_tag(int(vlan))
        port_obj.set_virtual_machine_interface_properties(vmi_props)
        kv_pairs = vnc_api.KeyValuePairs()
        vnic_kv = vnc_api.KeyValuePair(key='vnic_type', value='baremetal')
        kv_pairs.add_key_value_pair(vnic_kv)
        vpg_kv = vnc_api.KeyValuePair(key='vpg', value=vpg_name)
        kv_pairs.add_key_value_pair(vpg_kv)
        bind_kv = vnc_api.KeyValuePair(key='profile', value=json.dumps(ll_info))
        kv_pairs.add_key_value_pair(bind_kv)
        if native_vlan:
            vlan_kv = vnc_api.KeyValuePair(key='tor_port_vlan_id', value=native_vlan)
            kv_pairs.add_key_value_pair(vlan_kv)
        port_obj.set_virtual_machine_interface_bindings(kv_pairs)
        port_obj.set_virtual_machine_interface_device_owner(device_owner)
        try:
            self.vnc.virtual_machine_interface_create(port_obj)
            self.logger.info('Created port %s in port group %s'%(
                name, vpg_name))
        except vnc_api.RefsExistError:
            self.logger.debug('Port %s already exists'%(name))

    def extend_network_to_routers(self, network, routers):
        vn_obj = self.vn_objs[network]
        rtr_objs = dict()
        self.logger.debug('Extending network %s to routers %s'%(
            network, routers))
        for router in routers:
            rtr_obj = rtr_objs.get(router) or self.read_router(router)
            rtr_objs[router] = rtr_obj
            rtr_obj.add_virtual_network(vn_obj)
            self.vnc.physical_router_update(rtr_obj)

def _parse_args(args_str):
    keystone_auth_parser = SafeConfigParser()
    conf_file = keystone_auth_parser.read(
        '/etc/contrail/contrail-keystone-auth.conf')
    default_keystone_vals = {
        "username": "admin",
        "tenant_name": "admin",
        "domain_name": "Default"
    }
    get_vars = (lambda x: keystone_auth_parser.get('KEYSTONE', x)
                if keystone_auth_parser.has_option('KEYSTONE', x) else None)
    if conf_file:
        if keystone_auth_parser.has_section('KEYSTONE'):
            username = get_vars('admin_user')
            if username:
                default_keystone_vals['username'] = username
            password = get_vars('admin_password')
            if password:
                default_keystone_vals['password'] = password
            tenant_name = get_vars('admin_tenant_name')
            if tenant_name:
                default_keystone_vals['tenant_name'] = tenant_name
            domain_name = get_vars('user_domain_name')
            if domain_name:
                default_keystone_vals['domain_name'] = domain_name
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description='')
    parser.add_argument("--connections", required=True,
        help="Input yaml file with server connection details")
    parser.add_argument("--fabric", required=True,
        help="Name of the fabric")
    parser.add_argument("--debug",
        help="Run in debug mode, default False",
        action='store_true', default=False)
    parser.add_argument("--username",
        help="Username used to login to API Server")
    parser.add_argument("--password",
        help="Password used to login to API Server")
    parser.add_argument("--api-server-host",
        help="IP of API Server")
    parser.add_argument("--tenant-name",
        help="Name of Tenant")
    parser.add_argument("--domain-name",
        help="Domain name")
    ts = calendar.timegm(time.gmtime())
    if os.path.isdir("/var/log/contrail"):
        default_log = "/var/log/contrail/provision_infra_network-{0}.log".format(ts)
    else:
        import tempfile
        default_log = '{0}/provision_infra_network-{1}.log'.format(
            tempfile.gettempdir(), ts)
    parser.set_defaults(**default_keystone_vals)
    args_obj, _ = parser.parse_known_args(args_str.split())
    args_obj.log_file = default_log
    print('Logging at {0}'.format(default_log))
    return args_obj

def main():
    args = _parse_args(' '.join(sys.argv[1:]))
    provision_infra = ProvisionInfraNetwork(args)
    provision_infra.validate()
    provision_infra.create()

if __name__ == "__main__":
    main()

