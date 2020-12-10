#!/usr/bin/python

#
# Copyright (c) 2019 Juniper Networks, Inc. All rights reserved.
#

from builtins import object
import re

from netaddr import IPAddress


class FilterModule(object):
    def filters(self):
        return {
            'import_interface': self.import_interface
        }
    # end filters

    @classmethod
    def import_interface(cls, pb_input, device_info, ri_info):
        if not pb_input.get('interface_filters', []):
            pb_input.update({"interface_filters": [
                {
                    'op': 'regex',
                    'expr': '^xe|^ge|^et|^fxp|^xle|^fc|^fte|^ae|^reth|^lo0'
                }]})
        regex_list = []
        for flter in pb_input.get('interface_filters', []):
            if flter.get('op', '') == "regex":
                regex_list.append(flter.get('expr', ""))
        regex_str = '|'.join(regex_list)
        cf_interfaces_list = device_info.get(
            'configured_interfaces_info',
            {}).get(
            'config_parsed',
            {}) .get(
            'configuration',
            {}).get(
                'interfaces',
                {}).get(
                    'interface',
            {})
        rt_interfaces_list = device_info.get(
            'runtime_interfaces_info',
            {}).get(
            'parsed_output',
            {}) .get(
            'interface-information',
            {}).get(
                'physical-interface',
            {})
        ri_config = ri_info.get(
            'routing_instances_info',
            {}).get(
            'config_parsed',
            {}) .get(
            'configuration',
            {})
        if ri_config == '':
            ri_config = {}
        ri_list = ri_config.get('routing-instances', {}).get('instance', {})
        if isinstance(cf_interfaces_list, dict):
            cf_interfaces_list = [cf_interfaces_list]
        if isinstance(rt_interfaces_list, dict):
            rt_interfaces_list = [rt_interfaces_list]
        if isinstance(ri_list, dict):
            ri_list = [ri_list]
        rt_phy_interfaces_payloads = []
        rt_log_interfaces_payloads = []
        for phy_interface in rt_interfaces_list or []:
            if re.search(regex_str or ".*", phy_interface.get('name', '')):
                phy_interface_payload = {
                    "physical_interface_name": phy_interface.get('name', '')
                }
                physical_interface_port_id = phy_interface.get(
                    'snmp-index', '')
                if physical_interface_port_id:
                    phy_interface_payload.update(
                        {"physical_interface_port_id":
                         physical_interface_port_id})
                physical_interface_mac_address = phy_interface.get(
                    'current-physical-address', '')
                if physical_interface_mac_address:
                    phy_interface_payload.update(
                        {"physical_interface_mac_address":
                         physical_interface_mac_address})
                rt_phy_interfaces_payloads.append(phy_interface_payload)
                if 'logical-interface' in phy_interface:
                    log_intfs = phy_interface.get('logical-interface', {})
                    if isinstance(log_intfs, dict):
                        log_units = [log_intfs]
                    else:
                        log_units = log_intfs
                    for log_unit in log_units:
                        log_interface_payload = {
                            "physical_interface_name": phy_interface.get(
                                'name', ''),
                            "logical_interface_name": log_unit.get('name', '')}
                        add_fmly = log_unit.get('address-family', {})
                        if add_fmly:
                            log_type = "l3"
                            if isinstance(add_fmly, dict):
                                address_fmly_list = [add_fmly]
                            else:
                                address_fmly_list = add_fmly
                            for address_fmly in address_fmly_list:
                                if address_fmly.get(
                                        'address-family-name', '') \
                                        == "eth-switch":
                                    log_type = "l2"
                            log_interface_payload.update(
                                {"logical_interface_type": log_type})
                        rt_log_interfaces_payloads.append(
                            log_interface_payload)

        lo0_lb = '255.255.255.255'
        loopback = '255.255.255.255'
        primary_lb = '255.255.255.255'
        cf_phy_interfaces_payloads = []
        cf_log_interfaces_payloads = []
        lo_ri_map = dict()
        for ri in ri_list or []:
            if ri.get('instance-type', '') == 'vrf':
                intf_list = ri.get('interface', {})
                if isinstance(intf_list, dict):
                    intf_list = [intf_list]
                for intf in intf_list or []:
                    if intf.get('name', '').startswith("lo0."):
                        lo_ri_map[intf.get('name', '')] = ri.get('name', '')
        for phy_interface in cf_interfaces_list:
            phy_intf_name = phy_interface.get('name', '')
            regex_matched = re.search(regex_str or ".*", phy_intf_name)
            do_not_add_in_payload = False
            if regex_matched or 'lo0' in phy_intf_name:
                if not regex_matched:
                    do_not_add_in_payload = True
                else:
                    phy_interface_payload = {
                        "physical_interface_name": phy_intf_name
                    }
                    cf_phy_interfaces_payloads.append(phy_interface_payload)
                if 'unit' in phy_interface:
                    unit = phy_interface.get('unit', {})
                    if isinstance(unit, dict):
                        log_units = [unit]
                    else:
                        log_units = unit
                    for log_unit in log_units:
                        unit_name = log_unit.get('name', '')
                        log_interface_payload = {
                            "physical_interface_name": phy_intf_name,
                            "logical_interface_name": unit_name
                        }
                        if 'family' in log_unit:
                            if 'ethernet-switching' in log_unit.get(
                                    'family', {}):
                                log_interface_payload.update(
                                    {"logical_interface_type": "l2"})
                            else:
                                log_interface_payload.update(
                                    {"logical_interface_type": "l3"})
                                if 'inet' in log_unit.get(
                                        'family', {}) and 'address' in \
                                        log_unit.get(
                                        'family', {}). get(
                                        'inet', {}) and phy_intf_name == 'lo0'\
                                        and not (
                                        'lo0.' + unit_name in lo_ri_map):
                                    addr = log_unit.get(
                                        'family',
                                        {}).get(
                                        'inet',
                                        {}).get(
                                        'address',
                                        {})
                                    if isinstance(addr, dict):
                                        lo0_add_list = [addr]
                                    else:
                                        lo0_add_list = addr
                                    for lo0_add in lo0_add_list:
                                        ip = lo0_add.get(
                                            'name', '').split('/')[0]
                                        if ip != '127.0.0.1':
                                            if unit_name == '0':
                                                if lo0_add.get(
                                                        'primary', None) == '':
                                                    lo0_lb = ip
                                                    break
                                                elif IPAddress(ip) < \
                                                        IPAddress(lo0_lb):
                                                    lo0_lb = ip
                                                    continue
                                            elif lo0_lb == '255.255.255.255':
                                                if lo0_add.get(
                                                        'primary', None) == '':
                                                    if IPAddress(ip) <\
                                                            IPAddress(
                                                            primary_lb):
                                                        primary_lb = ip
                                                        break
                                                elif IPAddress(ip) < \
                                                        IPAddress(loopback) \
                                                        and primary_lb ==\
                                                        '255.255.255.255':
                                                    loopback = ip
                        if not do_not_add_in_payload:
                            cf_log_interfaces_payloads.append(
                                log_interface_payload)
        if lo0_lb != '255.255.255.255':
            loopback = lo0_lb
        elif primary_lb != '255.255.255.255':
            loopback = primary_lb
        elif loopback == '255.255.255.255':
            loopback = ''
        if pb_input.get('import_configured'):
            phy_interfaces_list = list(
                rt_phy_interfaces_payloads) + list(cf_phy_interfaces_payloads)
            log_interfaces_list = list(
                rt_log_interfaces_payloads) + list(cf_log_interfaces_payloads)
        else:
            phy_interfaces_list = list(rt_phy_interfaces_payloads)
            log_interfaces_list = list(rt_log_interfaces_payloads)
        return {
            "physical_interfaces_list": phy_interfaces_list,
            "logical_interfaces_list": log_interfaces_list,
            "dataplane_ip": str(loopback)
        }

# end FilterModule
