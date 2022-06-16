#! /usr/bin/env python

version = '1.1'

# This script provides some CLI commands mainly for troublelshooting prupose.
# It retrieves XML output from introspect services provided by Contrail main
# components e.g. control, config and comptue(vrouter) nodes and makes output
# CLI friendly.

import sys, os
import argparse
import socket, struct
import requests
try:
    from urllib.parse import urlencode # python3
except:
    from urllib import urlencode # python2
from datetime import datetime
from lxml import etree
from prettytable import PrettyTable
from uuid import UUID

debug = False
Default_Max_Width = 36
proxy = None
token = None

ServiceMap = {
    "vr": "contrail-vrouter-agent",
    "ctr": "contrail-control",
    "cfg_api": "contrail-api",
    "cfg_schema": "contrail-schema",
    "cfg_svcmon": "contrail-svc-monitor",
    "cfg_disc": "contrail-discovery",
    "collector": "contrail-collector",
    "alarm_gen": "contrail-alarm-gen",
    "dns": "contrail-dns",
    "qe": "contrail-query-engine",
    "dm": "contrail-device-manager",
    "nodemgr_cfg": "contrail-config-nodemgr",
    "nodemgr_db": "contrail-database-nodemgr",
    "nodemgr_ctr": "contrail-control-nodemgr",
    "nodemgr_vr": "contrail-vrouter-nodemgr",
}

class Introspect:
    def __init__ (self, host, port, filename):

        self.host_url = "http://" + host + ":" + str(port) + "/"
        self.filename = filename

    def get (self, path):
        """ get introspect output """
        self.output_etree = []

        # load xml output from given file
        if self.filename:
            try:
                print("Loadding from introspect xml %s" % self.filename)
                self.output_etree.append(etree.parse(self.filename))
            except Exception as inst:
                print("ERROR: parsing %s failed " % self.filename)
                print(inst)
                sys.exit(1)
        else:
            while True:
                url = self.host_url + path.replace(' ', '%20')
                headers = {}
                if proxy and token:
                    url = proxy + "/forward-proxy?" + urlencode({'proxyURL': url})
                    headers['X-Auth-Token'] = token
                if debug: print("DEBUG: retrieving url " + url)
                try:
                    response = requests.get(url,headers=headers)
                    response.raise_for_status()
                except requests.exceptions.HTTPError:
                    print('The server couldn\'t fulfill the request.')
                    print('URL: ' + url)
                    print('Error code: ', response.status_code)
                    print('Error text: ', response.text)
                    sys.exit(1)
                except requests.exceptions.RequestException as e:
                    print('Failed to reach destination')
                    print('URL: ' + url)
                    print('Reason: ', e)
                    sys.exit(1)
                else:
                    ISOutput = response.text
                    response.close()

                self.output_etree.append(etree.fromstring(ISOutput))

                if 'Snh_PageReq?x=' in path:
                    break

                # some routes output may be paginated
                pagination_path = "//Pagination/req/PageReqData"
                pagination = self.output_etree[-1].xpath(pagination_path)
                if len(pagination):
                    if (pagination[0].find("next_page").text is not None):
                        all = pagination[0].find("all").text
                        if(all is not None):
                            path = 'Snh_PageReq?x=' + all
                            self.output_etree = []
                            continue
                        else:
                            print("Warning: all page in pagination is empty!")
                            break
                    else:
                        break

                next_batch = self.output_etree[-1].xpath("//next_batch")

                if not len(next_batch):
                    break

                if (next_batch[0].text and next_batch[0].attrib['link']):
                    path = 'Snh_' + next_batch[0].attrib['link'] + \
                            '?x=' + next_batch[0].text
                else:
                    break
                if debug: print("instrosepct get completes\n")
        if debug:
            for tree in self.output_etree:
                etree.dump(tree)

    def printTbl(self, xpathExpr, max_width=Default_Max_Width, *args):
        """ print introspect output in a table.
            args lists interested fields. """
        items = []
        for tree in self.output_etree:
            items = items + tree.xpath(xpathExpr)
        if len(items):
            Introspect.dumpTbl(items, max_width, args)

    def printText(self, xpathExpr):
        """ print introspect output in human readable text """
        for tree in self.output_etree:
            for element in tree.xpath(xpathExpr):
                print(Introspect.elementToStr('', element).rstrip())

    @staticmethod
    def dumpTbl(items, max_width, columns):

        if not len(items):
            return

        if len(columns):
            fields = columns
        else:
            fields = [ e.tag for e in items[0] if e.tag != "more"]

        tbl = PrettyTable(fields)
        tbl.align = 'l'
        tbl.max_width = max_width
        for entry in items:
            row = []
            for field in fields:
                f = entry.find(field)
                if f is not None:
                    if f.text:
                        row.append(f.text)
                    elif list(f):
                        for e in f:
                            row.append(Introspect.elementToStr('', e).rstrip())
                    else:
                        row.append("n/a")
                else:
                    row.append("-")
            tbl.add_row(row)
        print(tbl)

    @staticmethod
    def elementToStr(indent, etreenode):
        """ convernt etreenode sub-tree into string """
        elementStr=''

        if etreenode.tag == 'more':   #skip more element
            return elementStr

        if etreenode.text and etreenode.tag == 'element':
            return indent + etreenode.text + "\n"
        elif etreenode.text:
            return indent + etreenode.tag + ': ' + \
                    etreenode.text.replace('\n', '\n' + \
                    indent + (len(etreenode.tag)+2)*' ') + "\n"
        elif etreenode.tag != 'list':
            elementStr += indent + etreenode.tag + "\n"

        if 'type' in etreenode.attrib:
            if etreenode.attrib['type'] == 'list' and \
                    etreenode[0].attrib['size'] == '0':
                return elementStr

        for element in etreenode:
            elementStr += Introspect.elementToStr(indent + '  ', element)

        return elementStr

    @staticmethod
    def pathToStr(indent, path, mode):

        path_info = ''
        if mode == 'raw':
            for item in path:
                 path_info += Introspect.elementToStr(indent, item)
            return path_info.rstrip()

        now = datetime.utcnow()

        path_modified = path.find("last_modified").text
        t1 = datetime.strptime(path_modified, '%Y-%b-%d %H:%M:%S.%f')
        path_age = str(now - t1).replace(',', '')
        path_proto = path.find("protocol").text
        path_source = path.find("source").text
        path_lp = path.find("local_preference").text
        path_as = path.find("as_path").text
        path_nh = path.find("next_hop").text
        path_label = path.find("label").text
        path_vn = path.find("origin_vn").text
        path_pri_tbl = path.find("primary_table").text
        path_vn_path = str(path.xpath("origin_vn_path/list/element/text()"))
        path_encap = str(path.xpath("tunnel_encap/list/element/text()"))
        path_comm = str(path.xpath("communities/list/element/text()"))
        path_sqn = path.find("sequence_no").text
        path_flags = path.find("flags").text

        path_info = ("%s[%s|%s] age: %s, localpref: %s, nh: %s, "
                     "encap: %s, label: %s, AS path: %s" %
                    (indent, path_proto, path_source, path_age, path_lp,
                     path_nh, path_encap, path_label, path_as))

        if mode == 'detail':
            path_info += ("\n%sprimary table: %s, origin vn: %s, "
                          "origin_vn_path: %s" %
                          (2*indent, path_pri_tbl, path_vn, path_vn_path))
            path_info += "\n%scommunities: %s" % (2*indent, path_comm)
            path_info += "\n%slast modified: %s" % (2*indent, path_modified)

        return path_info

    @staticmethod
    def routeToStr(indent, route, mode):

        route_info = ''
        now = datetime.utcnow()

        prefix = route.find("prefix").text
        prefix_modified = route.find("last_modified").text
        t1 = datetime.strptime(prefix_modified, '%Y-%b-%d %H:%M:%S.%f')
        prefix_age = str(now - t1).replace(',', '')

        route_info += "%s%s, age: %s, last_modified: %s" % \
                    (indent, prefix, prefix_age, prefix_modified)

        for path in route.xpath('.//ShowRoutePath'):
            route_info += "\n" + Introspect.pathToStr(indent*2, path, mode)

        return route_info.rstrip()

    def showRoute_VR(self, xpathExpr, family, address, mode):
        """ method to show route output from vrouter intropsect """
        indent = ' ' * 4

        ADDR_INET4 = 4
        ADDR_INET6 = 6
        ADDR_NONE = 0

        addr_type = ADDR_NONE
        if is_ipv4(address):
            addr_type = ADDR_INET4
        elif is_ipv6(address):
            addr_type = ADDR_INET6

        for tree in self.output_etree:
            for route in tree.xpath(xpathExpr):
                if 'inet' in family:
                    prefix = route.find("src_ip").text + '/' + \
                                route.find("src_plen").text
                else:
                    prefix = route.find("mac").text

                if family == 'inet' and addr_type == ADDR_INET4:
                    if not addressInNetwork(address, prefix):
                        if debug: print("DEBUG: skipping " + prefix)
                        continue
                elif family == 'inet6' and addr_type == ADDR_INET6:
                    if not addressInNetwork6(address, prefix):
                        if debug: print("DEBUG: skipping " + prefix)
                        continue

                if mode == "raw":
                    print(Introspect.elementToStr('', route).rstrip())
                    continue

                output = prefix + "\n"

                for path in route.xpath(".//PathSandeshData"):
                    nh = path.xpath("nh/NhSandeshData")[0]

                    peer = path.find("peer").text
                    pref = path.xpath("path_preference_data/"
                                      "PathPreferenceSandeshData/"
                                      "preference")[0].text

                    path_info = "%s[%s] pref:%s\n" % (indent, peer, pref)

                    path_info += indent + ' '
                    nh_type = nh.find('type').text
                    if nh_type == "interface":
                        mac = nh.find('mac').text
                        itf = nh.find("itf").text
                        label = path.find("label").text
                        path_info += ("to %s via %s, assigned_label:%s, "
                                        % (mac, itf, label))

                    elif nh_type == "tunnel":
                        tunnel_type = nh.find("tunnel_type").text
                        dip = nh.find("dip").text
                        sip = nh.find("sip").text
                        label = path.find("label").text
                        if nh.find('mac') is not None:
                            mac = nh.find('mac').text
                            path_info += ("to %s via %s dip:%s "
                                          "sip:%s label:%s, "
                                          % (mac, tunnel_type, dip,
                                             sip, label))
                        else:
                            path_info += ("via %s dip:%s sip:%s label:%s, "
                                          % (tunnel_type, dip, sip, label))

                    elif nh_type == "receive":
                        itf = nh.find("itf").text
                        path_info += "via %s, " % (itf)

                    elif nh_type == "arp":
                        mac = nh.find('mac').text
                        itf = nh.find("itf").text
                        path_info += "via %s, " % (mac)

                    elif 'Composite' in str(nh_type):
                        comp_nh = str(nh.xpath(".//itf/text()"))
                        path_info += "via %s, " % (comp_nh)

                    elif 'vlan' in str(nh_type):
                        mac = nh.find('mac').text
                        itf = nh.find("itf").text
                        path_info += "to %s via %s, " % (mac, itf)

                    nh_index = nh.find("nh_index").text
                    if nh.find("policy") is not None:
                        policy = nh.find("policy").text
                    else:
                        policy = ''
                    active_label = path.find("active_label").text
                    vxlan_id = path.find("vxlan_id").text
                    path_info += ("nh_index:%s , nh_type:%s, nh_policy:%s, "
                                  "active_label:%s, vxlan_id:%s" %
                                 (nh_index, nh_type, policy,
                                  active_label, vxlan_id))

                    if mode == "detail":
                        path_info += "\n"
                        path_info += indent + ' dest_vn:' + \
                            str(path.xpath("dest_vn_list/list/element/text()"))
                        path_info += ', sg:' + \
                            str(path.xpath("sg_list/list/element/text()"))
                        path_info += ', communities:' +  \
                            str(path.xpath("communities/list/element/text()"))
                    output += path_info + "\n"

                print(output.rstrip())

    def showRoute_CTR(self, last, mode):
        """ show route output from control node intropsect """
        indent = ' ' * 4
        now = datetime.utcnow()
        printedTbl = {}
        xpath_tbl = '//ShowRouteTable'
        xpath_rt = './/ShowRoute'
        xpath_pth = './/ShowRoutePath'
        for tree in self.output_etree:
            for table in tree.xpath(xpath_tbl):
                tbl_name = table.find('routing_table_name').text
                prefix_count = table.find('prefixes').text
                tot_path_count = table.find('paths').text
                pri_path_count = table.find('primary_paths').text
                sec_path_count = table.find('secondary_paths').text
                ifs_path_count = table.find('infeasible_paths').text

                if not(tbl_name in printedTbl):
                    print(("\n%s: %s destinations, %s routes "
                            "(%s primary, %s secondary, %s infeasible)"
                            % (tbl_name, prefix_count, tot_path_count,
                               pri_path_count, sec_path_count,
                               ifs_path_count)))
                    printedTbl[tbl_name] = True


                # start processing each route
                for route in table.xpath(xpath_rt):
                    paths = route.xpath(xpath_pth)
                    if not (len(paths)):
                        continue
                    prefix = route.find("prefix").text
                    prefix_modified = route.find("last_modified").text
                    t1 = datetime.strptime(prefix_modified,
                                           '%Y-%b-%d %H:%M:%S.%f')
                    prefix_age = str(now - t1).replace(',', '')

                    if (last and (now - t1).total_seconds() > last):
                        for path in paths:
                            path_modified = path.find("last_modified").text
                            t1 = datetime.strptime(path_modified,
                                                   '%Y-%b-%d %H:%M:%S.%f')
                            path_age = str(now - t1).replace(',', '')
                            if not ((now - t1).total_seconds() > last) :
                                print(("\n%s, age: %s, last_modified: %s" %
                                        (prefix, prefix_age, prefix_modified)))
                                print(Introspect.pathToStr(indent, path, mode))
                    else:
                        print(("\n%s, age: %s, last_modified: %s" %
                                (prefix, prefix_age, prefix_modified)))
                        for path in paths:
                            print(Introspect.pathToStr(indent, path, mode))

    def showSCRoute(self, xpathExpr):

        # fields = ['src_virtual_network',
        #             'dest_virtual_network',
        #             'service_instance',
        #             'state',
        #             'connected_route',
        #             'more_specifics',
        #             'ext_connecting_rt']
        fields = ['service_instance',
                  'state',
                  'connected_route',
                  'more_specifics',
                  'ext_connecting_rt']

        tbl = PrettyTable(fields)
        tbl.align = 'l'

        # start building the table
        for tree in self.output_etree:
            for sc in tree.xpath(xpathExpr):
                row = []
                for field in fields[0:2]:
                    f = sc.find(field)
                    if f is not None:
                        if f.text:
                            row.append(f.text)
                        elif list(f):
                            row.append(Introspect.elementToStr('', f).rstrip())
                        else:
                            row.append("n/a")
                    else:
                        row.append("non-exist")

                sc_xpath = ('./connected_route/ConnectedRouteInfo'
                            '/service_chain_addr')
                service_chain_addr = sc.xpath(sc_xpath)[0]
                row.append(Introspect.elementToStr('', service_chain_addr).rstrip())

                specifics = ''
                spec_xpath = './more_specifics/list/PrefixToRouteListInfo'
                PrefixToRouteListInfo = sc.xpath(spec_xpath)
                for p in PrefixToRouteListInfo:
                    specifics += ("prefix: %s, aggregate: %s\n" %
                                (p.find('prefix').text,
                                 p.find('aggregate').text))
                row.append(specifics.rstrip())

                ext_rt = ''
                ext_xpath = './ext_connecting_rt_info_list//ext_rt_prefix'
                ext_rt_prefix_list = sc.xpath(ext_xpath)
                for p in ext_rt_prefix_list:
                    ext_rt += p.text + "\n"
                row.append(ext_rt.rstrip())

                tbl.add_row(row)

        print(tbl)

    def showSCRouteDetail(self, xpathExpr):

        indent = ' ' * 4

        fields = ['src_virtual_network', 'dest_virtual_network',
                  'service_instance', 'src_rt_instance',
                  'dest_rt_instance', 'state']
        for tree in self.output_etree:

            for sc in tree.xpath(xpathExpr):

                for field in fields:
                    print("%s: %s" % (field, sc.find(field).text))

                print("connectedRouteInfo:")
                sc_xpath = ('./connected_route/ConnectedRouteInfo'
                            '/service_chain_addr')
                print(("%sservice_chain_addr: %s" %
                       (indent, sc.xpath(sc_xpath)[0].text)))
                for route in sc.xpath('./connected_route//ShowRoute'):
                    print(Introspect.routeToStr(indent, route, 'detail'))

                print("more_specifics:")
                specifics = ''
                spec_xpath = './more_specifics/list/PrefixToRouteListInfo'
                PrefixToRouteListInfo = sc.xpath(spec_xpath)
                for p in PrefixToRouteListInfo:
                    specifics += ("%sprefix: %s, aggregate: %s\n" %
                                  (indent, p.find('prefix').text,
                                   p.find('aggregate').text))
                print(specifics.rstrip())

                print("ext_connecting_rt_info_list:")
                ext_xpath = './/ExtConnectRouteInfo/ext_rt_svc_rt/ShowRoute'
                for route in sc.xpath(ext_xpath):
                    print(Introspect.routeToStr(indent, route, 'detail'))

                print(("aggregate_enable:%s\n" %
                       (sc.find("aggregate_enable").text)))

    def showStaticRoute(self, xpathExpr, format, max_width, columns):
        if not columns:
            columns = []
        if not max_width:
            max_width = Default_Max_Width
        for tree in self.output_etree:
            for entry in tree.xpath(xpathExpr):
                if format == 'table':
                    print('ri_name: %s' % (entry.find('ri_name').text))
                    Introspect.dumpTbl(entry.xpath("//StaticRouteInfo"),
                                       max_width, columns)
                else:
                    print(Introspect.elementToStr('', entry))

class CLI_basic(object):
    try:
        from sandesh_common.vns.constants import ServiceHttpPortMap
        IntrospectPortMap = ServiceHttpPortMap
    except:
        IntrospectPortMap = {
            "contrail-vrouter-agent" : 8085,
            "contrail-control" : 8083,
            "contrail-collector" : 8089,
            "contrail-query-engine" : 8091,
            "contrail-dns" : 8092,
            "contrail-api" : 8084,
            "contrail-api:0" : 8084,
            "contrail-schema" : 8087,
            "contrail-svc-monitor" : 8088,
            "contrail-device-manager" : 8096,
            "contrail-config-nodemgr" : 8100,
            "contrail-vrouter-nodemgr" : 8102,
            "contrail-control-nodemgr" : 8101,
            "contrail-database-nodemgr" : 8103,
            "contrail-storage-stats" : 8105,
            "contrail-ipmi-stats" : 8106,
            "contrail-inventory-agent" : 8107,
            "contrail-alarm-gen" : 5995,
            "contrail-alarm-gen:0" : 5995,
            "contrail-snmp-collector" : 5920,
            "contrail-topology" : 5921,
            "contrail-discovery" : 5997,
            "contrail-discovery:0" : 5997,
        }

    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument('-f', '--format',
                               choices=['table', 'text'],
                               default = 'table',
                               help='Output format.')
    common_parser.add_argument('-c', '--columns', nargs= '*',
                               help='Column(s) to include')
    common_parser.add_argument('--max_width', type=int,
                               help="Max width per column")

    def __init__(self, parser, host, port, filename):

        host = host or '127.0.0.1'
        if port is None:
            cli_type = type(self).__name__[4:]
            try:
                port = self.IntrospectPortMap[ServiceMap[cli_type]]
            except:
                port = self.IntrospectPortMap[ServiceMap[cli_type] + ':0']

        self.IST = Introspect(host, port, filename)

        self.subparser = parser.add_subparsers()

        subp = self.subparser.add_parser('status',
                                         help='Node/component status')
        subp.add_argument('-r', '--raw', action="store_true",
                          help='Display raw output')
        subp.set_defaults(func=self.SnhNodeStatus)

        subp = self.subparser.add_parser('cpu', help='CPU load info')
        subp.set_defaults(func=self.SnhCpuLoadInfo)

        subp = self.subparser.add_parser('trace', help='Sandesh trace buffer')
        subp.add_argument('name', nargs='?', help='Trace buffer name')
        subp.set_defaults(func=self.SnhTrace)

        subp = self.subparser.add_parser('uve',
                                          help='Sandesh UVE cache')
        subp.add_argument('name', nargs='?', type=str,
                          help='UVE type name')
        subp.set_defaults(func=self.SnhUve)

    def output_formatters(self, args, xpath, default_columns=[]):
        if args.format == 'text':
            self.IST.printText(xpath)
        else:
            max_width = args.max_width or Default_Max_Width
            if args.columns:
                self.IST.printTbl(xpath, max_width, *args.columns)
            else:
                self.IST.printTbl(xpath, max_width, *default_columns)

    def SnhNodeStatus(self, args):
        xpath = "//VnListReqSandeshData"
        self.IST.get('Snh_SandeshUVECacheReq?tname=NodeStatus')
        if args.raw:
            self.IST.printText('//NodeStatus')
        else:
            self.IST.printText('//ProcessStatus/module_id')
            self.IST.printText('//ProcessStatus/state')
            self.IST.printText('//ProcessStatus/description')
            self.IST.printTbl('//ConnectionInfo')
            self.IST.printTbl('//ProcessInfo')

    def SnhCpuLoadInfo(self, args):
        self.IST.get('Snh_CpuLoadInfoReq')
        self.IST.printText("//CpuLoadInfo/*")

    def SnhTrace(self, args):
        if not args.name:
            self.IST.get('Snh_SandeshTraceBufferListRequest')
            self.IST.printText('//trace_buf_name')
            #self.IST.printText('//*[not(*)]')
        else:
            self.IST.get('Snh_SandeshTraceRequest?x=' + str(args.name))
            self.IST.printText('//element')
            #self.IST.printText('//*[not(*)]')

    def SnhUve(self, args):
        if not args.name:
            self.IST.get('Snh_SandeshUVETypesReq')
            self.IST.printText('//type_name')
        else:
            self.IST.get('Snh_SandeshUVECacheReq?x=' + args.name)
            self.IST.printText('//*[@type="sandesh"]/data/*')

class CLI_cfg_api(CLI_basic):
    pass

class CLI_cfg_disc(CLI_basic):
    pass

class CLI_analytics(CLI_basic):
    pass

class CLI_alarm_gen(CLI_basic):
    pass

class CLI_dns(CLI_basic):
    pass

class CLI_qe(CLI_basic):
    pass

class CLI_dm(CLI_basic):
    pass

class CLI_nodemgr_cfg(CLI_basic):
    pass

class CLI_nodemgr_db(CLI_basic):
    pass

class CLI_nodemgr_ctr(CLI_basic):
    pass

class CLI_nodemgr_vr(CLI_basic):
    pass

class CLI_nodemgr_analytics(CLI_basic):
    pass

class CLI_cfg_schema(CLI_basic):

    def __init__(self, parser, host, port, filename):
        CLI_basic.__init__(self, parser, host, port, filename)
        self.add_parse_args()

    def add_parse_args(self):
        subp = self.subparser.add_parser('vn',
                                         parents = [self.common_parser],
                                         help='List Virtual Networks')
        subp.add_argument('name', nargs='?', default='',
                          help='Virtual Network name')
        subp.set_defaults(func=self.SnhVnList)

        subp = self.subparser.add_parser('ri',
                                         parents = [self.common_parser],
                                         help='List Routing Instances')
        subp.add_argument('name', nargs='?', default='',
                          help='Routing Instance name')
        subp.add_argument('-v', '--vn', default='',
                          help='Virtual Network name')
        subp.set_defaults(func=self.SnhRoutingInstanceList)

        subp = self.subparser.add_parser('sc', parents = [self.common_parser],
                                         help='List Service Chains')
        subp.add_argument('name', nargs='?', default='',
                          help='Service Chain name')
        subp.set_defaults(func=self.SnhServiceChainList)

        subp = self.subparser.add_parser('object',
                                         parents = [self.common_parser],
                                         help='List Schema-transformer Ojbects')
        subp.add_argument('name', nargs='?', default='',
                          help='object_id or fq_name')
        subp.add_argument('-t', '--type', default='',
                          help='Object type')
        subp.set_defaults(func=self.SnhStObjectReq)

    def SnhVnList(self, args):
        path = 'Snh_VnList?vn_name=%s' % (args.name)
        xpath = '//VirtualNetwork'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhRoutingInstanceList(self, args):
        path = ('Snh_RoutingInstanceList?vn_name=%s&ri_name=%s' %
                (args.vn, args.name))
        xpath = '//RoutingInstance'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhServiceChainList(self, args):
        path = 'Snh_ServiceChainList?sc_name=%s' % (args.name)
        xpath = '//ServiceChain'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhStObjectReq(self, args):
        path = ('Snh_StObjectReq?object_type=%s&object_id_or_fq_name=%s' %
                (args.type, args.name))
        xpath = '//StObject'
        self.IST.get(path)
        self.output_formatters(args, xpath)

class CLI_cfg_svcmon(CLI_basic):

    def __init__(self, parser, host, port, filename):
        CLI_basic.__init__(self, parser, host, port, filename)
        self.add_parse_args()

    def add_parse_args(self):
        subp = self.subparser.add_parser('si',
                                         parents = [self.common_parser],
                                         help='List service instances')
        subp.add_argument('name', nargs='?', default='',
                          help='Service instance name')
        subp.set_defaults(func=self.SnhServiceInstanceList)

    def SnhServiceInstanceList(self, args):
        path = 'Snh_ServiceInstanceList?si_name=%s' % (args.name)
        xpath = "//ServiceInstance"
        default_columns = ['name', 'si_type', 'si_state',
                           'vm_list', 'left_vn', 'right_vn']
        self.IST.get(path)
        self.output_formatters(args, xpath, default_columns)

class CLI_ctr(CLI_basic):

    def __init__(self, parser, host, port, filename):
        CLI_basic.__init__(self, parser, host, port, filename)
        self.add_parse_args()

    def add_parse_args(self):

        subp = self.subparser.add_parser('nei',
                                         parents = [self.common_parser],
                                         help='Show BGP/XMPPP neighbors')
        subp.add_argument('search', nargs='?', default='',type=str,
                          help='search string')
        subp.add_argument('-t', '--type',
                          choices=['BGP', 'XMPP'], default='',
                          help='Neighbor types (BGP or XMPP)')
        subp.set_defaults(func=self.SnhBgpNeighbor)

        subp = self.subparser.add_parser('ri',
                                         parents = [self.common_parser],
                                         help='Show routing instances')
        subp.add_argument('search', nargs='?', default='', type=str,
                          help='Search string')
        subp.set_defaults(func=self.SnhRoutingInstance)

        ## route sub parser
        route_parser = self.subparser.add_parser('route',
                                                 help='Show route info')
        rp = route_parser.add_subparsers()
        subp = rp.add_parser('summary',parents = [self.common_parser],
                             help='Show route summary')
        subp.add_argument('search', nargs='?', default='',
                             help='Only lists matched instances')
        subp.add_argument('--family', default='inet',
                             choices=['inet', 'inet6', 'evpn', 'ermvpn', 'all'],
                             help="Route family(default='%(default)s')")
        subp.set_defaults(func=self.SnhShowRouteSummary)

        subp = rp.add_parser('tables', help='List route table names')
        subp.add_argument('search', nargs='?', default='',
                              help='Only lists matched tables')
        subp.add_argument('-f', '--family', default='inet',
                              choices=['inet', 'inet6', 'evpn',
                                       'ermvpn', 'all'],
                              help="Route family(default='%(default)s')")
        subp.set_defaults(func=self.SnhShowRTable)

        subp = rp.add_parser('show', help='Show route')
        subp.add_argument('prefix', nargs='?', default='',
                          help='Show routes matching given prefix')
        subp.add_argument('-f', '--family',
                          choices=['inet', 'inet6', 'evpn', 'ermvpn',
                                   'rtarget', 'inetvpn', 'l3vpn'],
                          help='Show routes for given family.')
        subp.add_argument('-l', '--last', type=valid_period,
                          help=('Show routes modified during last time period'
                                ' (e.g. 10s, 5m, 2h, or 5d)'))
        subp.add_argument('-d', '--detail', action="store_true",
                          help='Display detailed output')
        subp.add_argument('-r', '--raw', action="store_true",
                          help='Display raw output in text')
        subp.add_argument('-p', '--protocol',
                          choices=['BGP', 'XMPP', 'local',
                                   'ServiceChain', 'Static'],
                          help='Show routes learned from given protocol')
        subp.add_argument('-v', '--vrf', default='',
                          help='Show routes in given routing instance '
                               'specified as fqn')
        subp.add_argument('-s', '--source', default='',
                          help='Show routes learned from given source')
        subp.add_argument('-t', '--table', default='',
                          help='Show routes in given table')
        subp.add_argument('--longer_match', action="store_true",
                          help='Shows more specific routes')
        subp.add_argument('--shorter_match', action="store_true",
                          help='Shows less specific routes')
        subp.set_defaults(func=self.SnhShowRoute)

        subp = rp.add_parser('static', parents = [self.common_parser],
                             help='Show static routes')
        subp.add_argument('search', nargs='?', default='',type=str,
                          help='search string')
        subp.set_defaults(func=self.SnhShowStaticRoute)

        subp = rp.add_parser('aggregate', parents = [self.common_parser],
                             help='Show aggregate routes')
        subp.add_argument('search', nargs='?', default='',type=str,
                          help='search string')
        subp.set_defaults(func=self.SnhShowRouteAggregate)

        ### end

        subp = self.subparser.add_parser('mcast',
                                         parents = [self.common_parser],
                                         help='Show multicast managers')
        subp.add_argument('type', choices=['table', 'tree'],
                          help="Show mcast table summary or tree for "
                               "given network")
        subp.add_argument('-t', '--table', default='',
                          help='Table string')
        subp.set_defaults(func=self.ShowMulticastManager)

        subp = self.subparser.add_parser('bgp_stats',
                                         help='Show BGP server stats')
        subp.set_defaults(func=self.ShowBgpServerReq)


        ## XMPP
        p_sub = self.subparser.add_parser('xmpp',
                                          parents = [self.common_parser],
                                          help='Show XMPP info')
        p_xmpp = p_sub.add_subparsers()

        subp = p_xmpp.add_parser('trace', help='XMPP message traces')
        subp.set_defaults(func=self.SnhXmppMsg)

        subp = p_xmpp.add_parser('stats', parents = [self.common_parser],
                                 help='XMPP server stats')
        subp.set_defaults(func=self.SnhXmppStats)

        subp = p_xmpp.add_parser('conn', parents = [self.common_parser],
                                 help='XMPP connections')
        subp.set_defaults(func=self.SnhXmppConn)

        ## IFMAP
        p_sub = self.subparser.add_parser('ifmap', help='Show IFMAP info')
        p_ifmap = p_sub.add_subparsers()

        subp = p_ifmap.add_parser('peer',
                                  parents = [self.common_parser],
                                  help='IFMAP peer server info')
        subp.add_argument('type', nargs='?',
                          choices=['server', 'server_conn', 'stats',
                                   'sm', 'ds_peer','all'],
                          default='all', help='Peer server info type')
        subp.set_defaults(func=self.IFMapPeerServerInfoReq)

        subp = p_ifmap.add_parser('client',
                                  parents = [self.common_parser],
                                  help='IFMAP xmpp clients info')
        subp.add_argument('client', nargs='?',
                                  help='client index or name')
        subp.add_argument('-t', '--type',
                                  choices=['node', 'link'],
                                  default='node',
                                  help='IFMAP data types')
        subp.add_argument('-s', '--search', default='',
                          help='search string')
        subp.add_argument('--history', action="store_true",
                          help='client history')
        subp.add_argument('-l', '--list', action="store_true",
                          help='list client name/index')
        subp.set_defaults(func=self.SnhXmppClient)

        subp = p_ifmap.add_parser('table', parents = [self.common_parser],
                                  help='IFMAP table  info')
        subp.add_argument('table', nargs='?', default='',
                          help='ifmap table e.g. access-control-list, '
                               'security-group etc')
        subp.add_argument('-s', '--search', default='', help='search string')
        subp.set_defaults(func=self.SnhIFMapTableShow)

        subp = p_ifmap.add_parser('node', parents = [self.common_parser],
                                  help='IFMAP node data info')
        subp.add_argument('search', nargs='?', default='',
                          help='List matched fqn')
        subp.add_argument('--fqn', default='', help='fq_node_name')
        subp.set_defaults(func=self.SnhIFMapNodeShow)

        subp = p_ifmap.add_parser('link', parents = [self.common_parser],
                                  help='IFMAP link data info')
        subp.add_argument('search', nargs='?', default='',
                          help='search string')
        subp.add_argument('-m', '--metadata', default='',
                          help='metadata string')
        subp.set_defaults(func=self.SnhIFMapLinkShow)

        subp = p_ifmap.add_parser('cm', parents = [self.common_parser],
                                  help='Channel manager info')
        subp.add_argument('type', choices=['stats', 'map'],
                          help='Show stats or channel map info')
        subp.set_defaults(func=self.SnhIFMapXmppShow)

        subp = p_ifmap.add_parser('pending_vm',
                                  parents = [self.common_parser],
                                  help='IFMap pending vm')
        subp.set_defaults(func=self.SnhIFMapPendingVmReg)

        ## ServiceChain
        subp = self.subparser.add_parser('sc',
                                         parents = [self.common_parser],
                                         help='Show ServiceChain info')
        subp.add_argument('search', nargs='?', default='',
                          help='search string')
        subp.add_argument('-d', '--detail', action="store_true",
                          default=False, help='Display detailed output')
        subp.add_argument('-r', '--route', action="store_true",
                          default=False, help='include route info.')
        subp.set_defaults(func=self.SnhSC)

        ## Config related
        parser_sub = self.subparser.add_parser('config',
                                               help='Show related config info')
        parser_config = parser_sub.add_subparsers()

        subp = parser_config.add_parser('ri', parents = [self.common_parser],
                                        help='Routing instances')
        subp.add_argument('search', nargs='?', default='',
                          type=str, help='Search string')
        subp.add_argument('-d', '--detail', action="store_true",
                          help='Display detailed output')
        subp.set_defaults(func=self.SnhShowBgpInstanceConfigReq)

        subp = parser_config.add_parser('rp', parents = [self.common_parser],
                                        help='Routing Policy')
        subp.add_argument('search', nargs='?', default='',
                          type=str, help='Search string')
        subp.set_defaults(func=self.SnhShowBgpRoutingPolicyConfigReq)

        subp = parser_config.add_parser('bgp', parents = [self.common_parser],
                                        help='BGP neighbor')
        subp.add_argument('search', nargs='?', default='',
                          type=str, help='Search string')
        subp.add_argument('-t', '--type',
                          choices=['bgpaas', 'fabric','all'], default='all',
                          help='filter by router_type. Default = all')
        subp.set_defaults(func=self.SnhShowBgpNeighborConfigReq)

        ## RT
        subp = self.subparser.add_parser('rt', parents = [self.common_parser],
                                         help='Show RtGroup info')
        subp.add_argument('search', nargs='?', default='',
                          help='search string')
        subp.add_argument('-d', '--detail', action="store_true",
                          default=False, help='Display detailed output')
        subp.set_defaults(func=self.SnhShowRtGroupReq)

    def SnhShowStaticRoute(self, args):
        path = 'Snh_ShowStaticRouteReq?search_string=%s' % (args.search)
        xpath = '//StaticRouteEntriesInfo'
        self.IST.get(path)
        self.IST.showStaticRoute(xpath, args.format, args.max_width,
                                 args.columns)

    def SnhShowRouteAggregate(self, args):
        path = 'Snh_ShowRouteAggregateReq?search_string=%s' % (args.search)
        xpath = '//aggregate_route_entries'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def ShowBgpServerReq(self, args):
        path = 'Snh_ShowBgpServerReq'
        xpath = '//ShowBgpServerResp/*'
        self.IST.get(path)
        self.IST.printText(xpath)

    def ShowMulticastManager(self, args):
        if args.type == 'tree' and not args.table:
            print("ERROR: Table name is required with -t option")
            return

        if args.type == 'table':
            path = ('Snh_ShowMulticastManagerReq?search_string=%s' %
                    (args.table))
            xpath = '//ShowMulticastManager'
            if not args.max_width:
                args.max_width = 60
        elif args.type == 'tree' and args.table:
            path = 'Snh_ShowMulticastManagerDetailReq?x=%s' % (args.table)
            xpath = '//ShowMulticastTree'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhShowRtGroupReq(self, args):
        if args.detail:
            path = 'Snh_ShowRtGroupReq?search_string=%s' % (args.search)
        else:
            path = 'Snh_ShowRtGroupSummaryReq?search_string=%s' % (args.search)
        self.IST.get(path)
        xpath = '//ShowRtGroupInfo'

        self.output_formatters(args, xpath)

    def SnhShowBgpNeighborConfigReq(self, args):
        path = ('Snh_ShowBgpNeighborConfigReq?search_string=%s'
                % (args.search))
        self.IST.get(path)
        xpath = '//ShowBgpNeighborConfig'
        if args.type == 'bgpaas':
            xpath += "[contains(router_type, '%s')]" % args.type
        elif args.type == 'fabric':
            xpath += "[router_type[not(normalize-space())]]"

        default_columns = ['name', 'admin_down', 'passive', 'router_type',
                           'local_as', 'autonomous_system', 'address',
                           'address_families', 'last_change_at']

        self.output_formatters(args, xpath, default_columns)

    def SnhShowBgpRoutingPolicyConfigReq(self, args):
        path = ('Snh_ShowBgpRoutingPolicyConfigReq?search_string=%s'
                % (args.search))
        self.IST.get(path)
        xpath = '//ShowBgpRoutingPolicyConfig'
        self.output_formatters(args, xpath)

    def SnhShowBgpInstanceConfigReq(self, args):
        path = 'Snh_ShowBgpInstanceConfigReq?search_string=%s' % (args.search)
        self.IST.get(path)
        xpath = '//ShowBgpInstanceConfig'

        default_columns = ['name', 'virtual_network_index', 'vxlan_id',
                           'import_target', 'export_target', 'has_pnf',
                           'last_change_at']
        self.output_formatters(args, xpath, default_columns)

    def SnhSC(self, args):
        self.IST.get('Snh_ShowServiceChainReq?search_string=' + args.search)
        xpath = '//ShowServicechainInfo'
        default_columns = ['src_virtual_network', 'dest_virtual_network',
                           'service_instance', 'src_rt_instance',
                           'dest_rt_instance', 'state']
        if args.route:
            if args.detail:
                self.IST.showSCRouteDetail(xpath)
            else:
                self.IST.showSCRoute(xpath)
        else:
            self.output_formatters(args, xpath, default_columns)

    def IFMapPeerServerInfoReq(self,args):
        args.format = 'text'
        path = 'Snh_IFMapPeerServerInfoReq?'
        if args.type == 'all':
            xpath = '//IFMapPeerServerInfoResp'
        else:
            xpath = '//%s_info' % (args.type)
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhIFMapTableShow(self, args):
        if not args.table and not args.search:
            path = 'Snh_IFMapNodeTableListShowReq'
            xpath = '//IFMapNodeTableListShowEntry'
            default_columns = []
        else:
            path = ('Snh_IFMapTableShowReq?table_name=%s&search_string=%s' %
                    (args.table, args.search))
            xpath = '//IFMapNodeShowInfo'
            default_columns = ['node_name', 'interests', 'advertised',
                               'dbentryflags', 'last_modified']
        self.IST.get(path)
        self.output_formatters(args, xpath, default_columns)

    def SnhIFMapLinkShow(self, args):
        path = ('Snh_IFMapLinkTableShowReq?search_string=%s&metadata=%s' %
                (args.search, args.metadata))
        self.IST.get(path)
        xpath = "//IFMapLinkShowInfo"
        self.output_formatters(args, xpath)

    def SnhIFMapNodeShow(self, args):
        if args.fqn:
            args.format = 'text'
            path = 'Snh_IFMapNodeShowReq?fq_node_name=%s' % (args.fqn)
            xpath = '//IFMapNodeShowInfo'
        else:
            args.format = 'text'
            path = 'Snh_IFMapTableShowReq?search_string=%s' % (args.search)
            xpath = '//node_name'

        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhIFMapXmppShow(self, args):
        path = 'Snh_IFMapXmppShowReq?'
        if args.type == 'stats':
            xpath = '//IFMapChannelManagerStats'
            args.format = 'text'
        else:
            xpath = '//IFMapXmppChannelMapEntry'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhIFMapPendingVmReg(self, args):
        path = 'Snh_IFMapPendingVmRegReq?'
        xpath = '//IFMapPendingVmRegResp'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhXmppClient(self, args):
        default_columns = []
        xpath = []
        if args.list:
            path = 'Snh_IFMapServerClientShowReq'
            xpath.append('//IFMapServerClientMapShowEntry')
            xpath.append('//IFMapServerIndexMapShowEntry')
        elif args.history:
            path = 'Snh_IFMapServerClientShowReq'
            xpath.append('//IFMapServerClientHistoryEntry')
        elif args.client is None:
            path = 'Snh_IFMapXmppClientInfoShowReq'
            default_columns = ["client_name", "client_index", "vm_reg_info",
                               "msgs_blocked", "is_blocked"]
            xpath.append('//IFMapXmppClientInfo')
        else:
            if args.type == 'node':
                path = ('Snh_IFMapPerClientNodesShowReq?'
                         'client_index_or_name=%s&search_string=%s' %
                         (args.client, args.search))
                xpath.append('//IFMapPerClientNodesShowInfo')
            else:
                path = ('Snh_IFMapPerClientLinksShowReq?'
                         'client_index_or_name=%s&search_string=%s' %
                         (args.client, args.search))
                xpath.append('//IFMapPerClientLinksShowInfo')

        self.IST.get(path)
        for p in xpath:
            self.output_formatters(args, p, default_columns)

    def SnhXmppMsg(self, args):
        self.IST.get('Snh_SandeshTraceRequest?x=XmppMessageTrace')
        self.IST.printText('//element')

    def SnhXmppStats(self, args):
        self.IST.get('Snh_ShowXmppServerReq')
        self.output_formatters(args, '//ShowXmppServerResp')

    def SnhXmppConn(self, args):
        self.IST.get('Snh_ShowXmppConnectionReq')
        self.output_formatters(args, '//ShowXmppConnection')

    def SnhBgpNeighbor(self, args):
        self.IST.get('Snh_BgpNeighborReq?search_string=' + args.search)

        if args.type:
            xpath = "//BgpNeighborResp[encoding='" + args.type + "']"
        else:
            xpath = "//BgpNeighborResp"

        default_columns = ["peer", "peer_address", "peer_asn", "encoding",
                           "peer_type", "state", "send_state", "flap_count",
                           "flap_time"]

        self.output_formatters(args, xpath, default_columns)

    def SnhRoutingInstance(self, args):
        self.IST.get('Snh_ShowRoutingInstanceReq?search_string=' + args.search)
        xpath = "//ShowRoutingInstance"

        default_columns = ["name", "vn_index", "vxlan_id", "import_target",
                           "export_target", "routing_policies"]

        self.output_formatters(args, xpath, default_columns)


    def SnhShowRouteSummary(self, args):
        self.IST.get('Snh_ShowRouteSummaryReq?search_string=' + args.search)
        xpath = "//ShowRouteTableSummary"
        if args.family != 'all':
            xpath += "[contains(name, '%s.0')]" % args.family

        default_columns = ["name", "prefixes", "paths", "primary_paths",
                           "secondary_paths", "infeasible_paths"]

        if not args.max_width:
            args.max_width = 50

        self.output_formatters(args, xpath, default_columns)

    def SnhShowRTable(self, args):
        self.IST.get('Snh_ShowRouteSummaryReq?search_string=' + args.search)
        xpath = "//ShowRouteTableSummary/name"
        if args.family != 'all':
            xpath = ("//ShowRouteTableSummary[contains(name, '%s.0')]/name" %
                     args.family)

        self.IST.printText(xpath)

    def SnhShowRoute(self, args):
        shorter_match = ''
        longer_match = ''
        if is_ipv4(args.prefix):
            args.prefix = args.prefix + '%2F32'
            args.shorter_match = True
        elif is_ipv6(args.prefix):
            args.prefix = args.prefix + '%2F128'
            args.shorter_match = True

        if args.shorter_match:
            shorter_match = '1'
        if args.longer_match:
            longer_match = '1'

        protocol = args.protocol or ''
        family = args.family or ''

        path = ('Snh_ShowRouteReq?'
                'routing_table=%s&routing_instance=%s&prefix=%s'
                '&longer_match=%s&shorter_match=%s&count='
                '&start_routing_table=&start_routing_instance='
                '&start_prefix=&source=%s&protocol=%s&family=%s' %
                (args.table, args.vrf, args.prefix,
                 longer_match, shorter_match, args.source,
                 protocol, family ))

        self.IST.get(path)

        if args.detail:
            mode = 'detail'
        elif args.raw:
            mode = 'raw'
        else:
            mode ='brief'

        # Family/source/protocl match is supported only from 3.2.
        # To handle the same in older releases, pass the prarmeters
        # to showrouter method
        self.IST.showRoute_CTR(args.last, mode)

class CLI_vr(CLI_basic):
    def __init__(self, parser, host, port, filename):
        CLI_basic.__init__(self, parser, host, port, filename)
        self.add_parse_args()

    def add_parse_args(self):

        ## show interfaces
        subp = self.subparser.add_parser('intf',
                                         parents = [self.common_parser],
                                         help='Show vRouter interfaces')
        subp.add_argument('search', nargs='?', default='',
                          help='Search string')
        subp.add_argument('-u', '--uuid', default='', help='Interface uuid')
        subp.add_argument('-v', '--vn', default='', help='Virutal network')
        subp.add_argument('-n', '--name', default='', help='Interface name')
        subp.add_argument('-m', '--mac', default='', help='VM mac address')
        subp.add_argument('-i', '--ipv4', default='', help='VM IP address')
        subp.set_defaults(func=self.SnhItf)

        ## show kinterfaces
        subp = self.subparser.add_parser('kintf',
                                         parents = [self.common_parser],
                                         help='Show vRouter interfaces')
        subp.add_argument('search', nargs='?', default='',
                          help='Search string')
        subp.add_argument('-u', '--uuid', default='', help='Interface uuid')
        subp.add_argument('-v', '--vn', default='', help='Virutal network')
        subp.add_argument('-n', '--name', default='', help='Interface name')
        subp.add_argument('-m', '--mac', default='', help='VM mac address')
        subp.add_argument('-i', '--ipv4', default='', help='VM IP address')
        subp.set_defaults(func=self.SnhKInterfaceReq)

        ## show vn
        subp = self.subparser.add_parser('vn',parents = [self.common_parser],
                                         help='Show Virtual Network')
        #vn = vn_parser.add_subparsers()
        #subp = vn.add_parser('vxlan', parents = [self.common_parser],help='vxlan info')
        subp.add_argument('name', nargs='?', default='', help='VN name')
        subp.add_argument('-uv', '--vnuuid', default='', help='VN uuid')
        subp.add_argument('-vx','--vxlan_id', default='',help='VxLan')
        #subp.add_argument('id', nargs='?', type=int, help='vxlan uuid')
        subp.add_argument('-ipa','--ipam_name',default='',help='ipam')
        subp.set_defaults(func=self.SnhVn)

        subp = self.subparser.add_parser('vrf',
                                         parents = [self.common_parser],
                                         help='Show VRF')
        subp.add_argument('name', nargs='?', default='', help='VRF name')
        subp.set_defaults(func=self.SnhVrf)

        subp = self.subparser.add_parser('all',parents = [self.common_parser],help='Show All' '(route&config) status' '(dns) status')
        subp.add_argument('name', nargs='?', default='',help='All')
        subp.add_argument('search', nargs='?', default='',
                          help='Search string')
        subp.add_argument('-u', '--uuid', default='', help='Interface uuid')
        subp.add_argument('-v', '--vn', default='', help='Virutal network')
        subp.add_argument('-n', '--name', default='', help='Interface name')
        subp.add_argument('-m', '--mac', default='', help='VM mac address')
        subp.add_argument('-i', '--ipv4', default='', help='VM IP address')
        subp.add_argument('address', nargs='?', default='',
                          help='Address')
        subp.add_argument('-vr', '--vrf', type=int, default=0,
                          help='VRF index, default: 0 (IP fabric)')
        subp.add_argument('-fa', '--family',
                          choices=['inet', 'inet6','bridge','layer2', 'evpn'],
                          default='',
                          help='Route family')
        subp.add_argument('-p', '--prefix', default='/',
                          help='IPv4 or IPv6 prefix')
        subp.add_argument('-d', '--detail', action="store_true",
                          help='Display detailed output')
        subp.add_argument('-r', '--raw', action="store_true",
                          help='Display raw output in plain text')
        subp.add_argument('-t', '--table', default='',
                                  help='Table names. e.g. virtual-router, '
                                       'virtual-machine-interface, '
                                       'virtual-machine, instance-ip')
        subp.add_argument('-no', '--node', default='', help='Node sub string')
        subp.add_argument('-l', '--link_type', default='',
                          help='Link type sub string')
        subp.add_argument('-ln', '--link_node', default='',
                          help='Link node sub string')
        subp.add_argument('type', nargs='?',
                          choices=['ipc', 'pkt', 'flow', 'xmpp',
                                   'sandesh', 'ifmap', 'all'],
                          default = 'all',
                          help='Stats type, default: all')
        subp.add_argument('index', nargs='?', type=int,
                          help='NH index')
        subp.add_argument('-ty', '--type',
                          choices=['arp', 'discard', 'receive', 'resolve',
                                   'l2-receive', 'interface', 'tunnel',
                                   'composite'], help='NH type')
        subp.add_argument('-py', '--policy', choices=['enabled', 'disabled'],
                          help='NH policy')
        subp.add_argument('label', nargs='?', type=int,
                          help='MPLS label value')
        subp.add_argument('-z', '--ztype',
                          choices=['arp', 'discard', 'receive', 'resolve',
                                   'l2-receive', 'interface', 'tunnel',
                                   'composite'],
                          help='NH type')
        #subp.add_argument('uuidvrf', nargs='?', type=validate_uuid,
             #             help='vrfassign uuid')
        subp.set_defaults(func=self.SnhAll)
        ## show routes
        subp = self.subparser.add_parser('route', help='Show routes')
        subp.add_argument('address', nargs='?', default='',
                          help='Address')
        subp.add_argument('-v', '--vrf', type=int, default=0,
                          help='VRF index, default: 0 (IP fabric)')
        subp.add_argument('-f', '--family',
                          choices=['inet', 'inet6','bridge','layer2', 'evpn'],
                          default='',
                          help='Route family')
        subp.add_argument('-p', '--prefix', default='/',
                          help='IPv4 or IPv6 prefix')
        subp.add_argument('-d', '--detail', action="store_true",
                          help='Display detailed output')
        subp.add_argument('-r', '--raw', action="store_true",
                          help='Display raw output in plain text')
        subp.set_defaults(func=self.SnhRoute)

        ## show security groups
        subp = self.subparser.add_parser('sg',
                                         parents = [self.common_parser],
                                         help='Show Security Groups')
        subp.set_defaults(func=self.SnhSg)

        subp = self.subparser.add_parser('acl',
                                         parents = [self.common_parser],
                                         help='Show ACL info')
        subp.add_argument('uuid', nargs='?', default='', help='ACL uuid')
        subp.set_defaults(func=self.SnhAcl)

        ## show health check
        subp = self.subparser.add_parser('hc',
                                         parents = [self.common_parser],
                                         help='Health Check info')
        subp.add_argument('uuid', nargs='?', default='', help='HC uuid')
        subp.set_defaults(func=self.SnhHealthCheck)

        ## show ifmap
        subp = self.subparser.add_parser('ifmap', help='IFMAP info')
        subp.add_argument('-t', '--table', default='',
                                  help='Table names. e.g. virtual-router, '
                                       'virtual-machine-interface, '
                                       'virtual-machine, instance-ip')
        subp.add_argument('-n', '--node', default='', help='Node sub string')
        subp.add_argument('-l', '--link_type', default='',
                          help='Link type sub string')
        subp.add_argument('-ln', '--link_node', default='',
                          help='Link node sub string')
        subp.set_defaults(func=self.SnhShowIFMap)

        ## show baas
        subp = self.subparser.add_parser('baas',
                                         parents = [self.common_parser],
                                         help='Bgp As A Service info')
        subp.set_defaults(func=self.SnhBaaS)

        subp = self.subparser.add_parser('xmpp',
                                         parents = [self.common_parser],
                                         help='Show Agent XMPP connections '
                                         '(route&config) status')
        subp.set_defaults(func=self.SnhXmpp)

        ## show xmpp dns
        subp = self.subparser.add_parser('xmpp-dns',
                                         parents = [self.common_parser],
                                         help='Show Agent XMPP connections '
                                              '(dns) status')
        subp.set_defaults(func=self.SnhDNSXmpp)

        ## show vrouter agnet stats
        subp = self.subparser.add_parser('stats',
                                         parents = [self.common_parser],
                                         help='Show Agent stats')
        subp.add_argument('type', nargs='?',
                          choices=['ipc', 'pkt', 'flow', 'xmpp',
                                   'sandesh', 'ifmap', 'all'],
                          default = 'all',
                          help='Stats type, default: all')
        subp.set_defaults(func=self.SnhAgentStats)

        ## show service related info
        subp = self.subparser.add_parser('service',
                                         parents = [self.common_parser],
                                         help='Service related info')
        subp.add_argument('name', nargs='?',
                          choices = ["Icmp", "Icmpv6", "Dhcp", "Dhcpv6",
                                     "Dns", "Arp", "Metadata", "ShowAll"],
                          default = "ShowAll",
                          help='Service name')
        subp.add_argument('--pkt', action="store_true",
                          help='Show packet trace details')
        subp.add_argument('--intf', action="store_true",
                          help='Show Arp stats per interface')
        subp.add_argument('--cache', action="store_true",
                          help='Show Arp cache')
        subp.add_argument('--garp_cache', action="store_true",
                          help='Show Gratuitous Arp cache')
        subp.set_defaults(func=self.SnhService)

        ## show service Instances
        subp = self.subparser.add_parser('si',
                                         parents = [self.common_parser],
                                         help='Service instance info')
        subp.add_argument('uuid', nargs='?', type=validate_uuid,
                          help='Service instance uuid')
        subp.set_defaults(func=self.SnhServiceInstance)

        ## show nh info
        subp = self.subparser.add_parser('nh',
                                         parents = [self.common_parser],
                                         help='NextHop info')
        subp.add_argument('index', nargs='?', type=int,
                          help='NH index')
        subp.add_argument('-t', '--type',
                          choices=['arp', 'discard', 'receive', 'resolve',
                                   'l2-receive', 'interface', 'tunnel',
                                   'composite'],
                          help='NH type')
        subp.add_argument('-p', '--policy', choices=['enabled', 'disabled'],
                          help='NH policy')
        subp.set_defaults(func=self.SnhNhList)

        ## show vm info
        subp = self.subparser.add_parser('vm',
                                         parents = [self.common_parser],
                                         help='VM info')
        subp.add_argument('uuid', nargs='?', type=validate_uuid,
                          help='VM uuid')
        subp.set_defaults(func=self.SnhVmList)

        ## show mpls info
        subp = self.subparser.add_parser('mpls',
                                         parents = [self.common_parser],
                                         help='MPLS info')
        subp.add_argument('label', nargs='?', type=int,
                          help='MPLS label value')
        subp.add_argument('-z', '--ztype',
                          choices=['arp', 'discard', 'receive', 'resolve',
                                   'l2-receive', 'interface', 'tunnel',
                                   'composite'],
                          help='NH type')
        subp.set_defaults(func=self.SnhMpls)

        ## show vrfassign lists
        subp = self.subparser.add_parser('vrfassign',
                                         parents = [self.common_parser],
                                         help='VrfAssign info')
        subp.add_argument('uuid', nargs='?', type=validate_uuid,
                          help='vrfassign uuid')
        subp.set_defaults(func=self.SnhVrfAssign)

        ## show LinkLocalServiceInfo
        subp = self.subparser.add_parser('linklocal',
                                         parents = [self.common_parser],
                                         help='LinkLocal service info')
        subp.set_defaults(func=self.SnhLinkLocalServiceInfo)

        ## show vxlan
        vxlan_parser = self.subparser.add_parser('vxlan', help='vxlan info')
        vp = vxlan_parser.add_subparsers()
        subp = vp.add_parser('nh', parents = [self.common_parser],
                             help='NH info')
        subp.add_argument('id', nargs='?', type=int, help='vxlan uuid')
        subp.set_defaults(func=self.SnhVxLan)

        subp = vp.add_parser('config', parents = [self.common_parser],
                             help='Config info')
        subp.add_argument('id', nargs='?', type=int, help='vxlan uuid')
        subp.add_argument('--vn', default='', type=str, help='vn')
        subp.add_argument('--active', default='', type=str, help='active')

        subp.set_defaults(func=self.SnhVxLanConfig)


        ## show mirror
        mirror_parser = self.subparser.add_parser('mirror', help='mirror info')
        mp = mirror_parser.add_subparsers()
        subp = mp.add_parser('vn', parents = [self.common_parser],
                             help='NH info')
        subp.add_argument('name', nargs='?', default='', help='vn name')
        subp.set_defaults(func=self.Snh_MirrorCfgVnInfoReq)

        subp = mp.add_parser('intf', parents = [self.common_parser],
                             help='Config info')
        subp.add_argument('handle', nargs='?', default='', help='handle')
        subp.set_defaults(func=self.Snh_IntfMirrorCfgDisplayReq)

    def Snh_MirrorCfgVnInfoReq(self, args):
        path = 'Snh_MirrorCfgVnInfoReq?vn_name=%s' % (args.name)
        xpath = 'VnAclInfo'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def Snh_IntfMirrorCfgDisplayReq(self, args):
        path = 'Snh_IntfMirrorCfgDisplayReq?handle=%s' % (args.handle)
        xpath = 'IntfMirrorCfgSandesh'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhVxLanConfig(self, args):
        id = str(args.id) or ''
        path = ('Snh_VxLanConfigReq?vxlan_id=%s&vn=%s&active=%s' %
                (id, args.vn, args.active))
        xpath = '//VxLanConfigEntry'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhVxLan(self, args):
        if (args.id):
            id = str(args.id) or ''
        else:
            id = None
        path = 'Snh_VxLanReq'
        if (id):
            path += '?vxlan_id=%s' % (id)
        xpath = '//VxLanSandeshData'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhLinkLocalServiceInfo(self, args):
        path = 'Snh_LinkLocalServiceInfo'
        xpath = '//LinkLocalServiceData'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhVrfAssign(self, args):
        uuid = args.uuid or ''
        path = 'Snh_VrfAssignReq?uuid=%s' % (uuid)
        xpath = '//vrf_assign_list'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhMpls(self, args):
        ztype = args.ztype or ''
        if (args.label):
          label = str(args.label) or ''
        else:
          label = None
        path = 'Snh_MplsReq?type=%s' % (ztype)
        if (label):
          path += '&label=%s' % (label)
        xpath = '//MplsSandeshData'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhVmList (self, args):
        uuid = args.uuid or ''
        path = 'Snh_VmListReq?uuid=%s' % (uuid)
        xpath = '//VmSandeshData'
        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhNhList(self, args):
        if (args.index):
            index = str(args.index) or ''
        else:
            index = None
        type = args.type or ''
        policy = args.policy or ''
        path = 'Snh_NhListReq?type=%s' % (type)
        if (index):
            path += '&nh_index=%s' % (index) ## always need to be 2nd
        path += '&policy_enabled=%s' % (policy)
        xpath = '//NhSandeshData'
        default_columns = ['type', 'nh_index', 'policy', 'itf', 'mac', 'vrf',
                           'valid', 'ref_count', 'mc_list']

        self.IST.get(path)
        self.output_formatters(args, xpath, default_columns)

    def SnhServiceInstance(self, args):
        uuid = args.uuid or ''
        path = 'Snh_ServiceInstanceReq?uuid=%s' % (uuid)
        xpath = '//ServiceInstanceSandeshData'
        default_columns = ['uuid', 'service_type', 'virtualization_type',
                           'instance_id', 'vmi_inside', 'vmi_outside']
        self.IST.get(path)
        self.output_formatters(args, xpath, default_columns)

    def SnhItf(self, args):
        path = 'Snh_ItfReq?name=' + args.name + '&type=&uuid=' \
                + args.uuid + '&vn=' + args.vn + '&mac=' + args.mac \
                + '&ipv4_address=' + args.ipv4
        self.IST.get(path)

        xpath = "//ItfSandeshData"
        if args.search: xpath += "[contains(., '%s')]" % args.search

        default_columns = ["index", "name", "active", "mac_addr", "ip_addr",
                           "mdata_ip_addr", "vm_name", "vn_name"]

        self.output_formatters(args, xpath, default_columns)

    def SnhKInterfaceReq(self, args):
        path = 'Snh_KInterfaceReq'
        self.IST.get(path)

        xpath = "//KInterfaceInfo"
        if args.search: xpath += "[contains(., '%s')]" % args.search

        default_columns = ["idx", "type", "flag", "vrf", "rid",
                           "os_idx", "mtu", "name"]

        self.output_formatters(args, xpath, default_columns)

    def SnhVn(self, args):
#	print("Printing VN")
        #path = 'Snh_VnListReq?name=' + args.name + '&vnuuid=' + args.vnuuid +'&vxlan_id=' + args.vxlan_id + '&ipam_name=' + args.ipam_name
        path = 'Snh_VnListReq?name=' + args.name + '&vnuuid=' + args.vnuuid +'&vxlan_id=' + '&ipam_name='
        self.IST.get(path)
        xpath = "//VnSandeshData"
        default_columns = ["name", "uuid", "layer2_forwarding",
                           "ipv4_forwarding", "enable_rpf", "bridging"]

        self.output_formatters(args, xpath, default_columns)

    def SnhVrf(self, args):
        path = 'Snh_VrfListReq?name=' + args.name
        self.IST.get(path)

        xpath = "//VrfSandeshData"
        default_columns = ["name", "ucindex", "mcindex", "brindex",
                           "evpnindex", "vxlan_id", "vn"]

        self.output_formatters(args, xpath, default_columns)

    def SnhAll(self, args):
        print("Printing Status info")
        self.SnhNodeStatus(args)
        print("\nPrinting CPU Load Info")
        self.SnhCpuLoadInfo(args)
        print("\nPrinting Intf")
        self.SnhItf(args)
        print("\nPrinting vrf")
        self.SnhVrf(args)
        print("\nPrinting route")
        self.SnhRoute(args)
        print("\nPrinting Acl")
        self.SnhAcl(args)
        print("\nPrinting Ifmap")
        self.SnhShowIFMap(args)
        print("\nPrinting Xmpp info")
        self.SnhXmpp(args)
        print("\nPrinting Xmpp-DNS data")
        self.SnhDNSXmpp(args)
        print("\nPrinting Agent Stats")
        self.SnhAgentStats(args)
        print("\nPrinting nh Info")
        self.SnhNhList(args)
        print("\nPrinting mpls Info")
        self.SnhMpls(args)

    def SnhTraceAll(self, args):
        print("Printing Trace options")
        self.SnhTrace(args)
        print("\nPrinting Acl info")
        self.SnhAcl(args)

    def SnhSg(self, args):
        self.IST.get('Snh_SgListReq')
        xpath = "//SgSandeshData"
        self.output_formatters(args, xpath)

    def SnhAcl(self, args):
        self.IST.get('Snh_AclReq?uuid=' + args.uuid)
        xpath = "//AclSandeshData"
        default_columns = ["uuid", "name", "dynamic_acl"]
        self.output_formatters(args, xpath, default_columns)

    def SnhXmpp(self, args):
        print("Hello")
        self.IST.get('Snh_AgentXmppConnectionStatusReq')

        xpath = "//AgentXmppData"
        default_columns = ["controller_ip", "state", "peer_name",
                           "peer_address", "cfg_controller",
                           "flap_count", "flap_time"]

        self.output_formatters(args, xpath, default_columns)

    def SnhDNSXmpp(self, args):
        self.IST.get('Snh_AgentDnsXmppConnectionStatusReq')

        xpath = "//AgentXmppDnsData"
        default_columns = ["dns_controller_ip", "state", "peer_name",
                           "peer_address", "flap_count", "flap_time"]

        self.output_formatters(args, xpath, default_columns)

    def SnhRoute(self, args):

        if args.family =='':
            if args.address == '' or is_ipv4(args.address):
                args.family = 'inet'
            elif is_ipv6(args.address):
                args.family = 'inet6'
            else:
                args.family = 'layer2'

        if args.family == 'inet':
            p=args.prefix.split('/')
            if len(p) == 1: p.append('32')
            path = ('Snh_Inet4UcRouteReq?vrf_index=' + str(args.vrf) +
                   '&src_ip=' + p[0] + '&prefix_len=' + p[1] + '&stale=')
            xpath = '//RouteUcSandeshData'
            if args.address and not is_ipv4(args.address):
                xpath += "[contains(src_ip, '%s')]" % args.address

        elif args.family == 'inet6':
            p=args.prefix.split('/')
            if len(p) == 1: p.append('128')
            path = ('Snh_Inet6UcRouteReq?vrf_index=' + str(args.vrf) +
                   '&src_ip=' + p[0] + '&prefix_len=' + p[1] + '&stale=')
            xpath = '//RouteUcSandeshData'
            if args.address and not is_ipv6(args.address):
                xpath += "[contains(src_ip, '%s')]" % args.address

        else:
            mapping = {
                'bridge': ['Snh_BridgeRouteReq?vrf_index=',
                           '//RouteL2SandeshData'],
                'evpn': ['Snh_EvpnRouteReq?vrf_index=',
                         '//RouteEvpnSandeshData'],
                'layer2': ['Snh_Layer2RouteReq?vrf_index=',
                           '//RouteL2SandeshData']
            }
            path = mapping.get(args.family, '')[0] + str(args.vrf)
            xpath = mapping.get(args.family, '')[1]
            if args.address: xpath += "[contains(mac, '%s')]" % args.address

        if args.detail:
            mode = 'detail'
        elif args.raw:
            mode = 'raw'
        else:
            mode ='brief'

        self.IST.get(path)
        self.IST.showRoute_VR(xpath, args.family, args.address, mode)

    def SnhAgentStats(self, args):
        StatsMap = {
            'ipc': '//IpcStatsResp',
            'pkt': '//PktTrapStatsResp',
            'flow': '//FlowStatsResp',
            'xmpp': '//XmppStatsInfo',
            'sandesh': '//SandeshStatsResp',
        }
        if args.type == 'all':
            # As tables are too big, force output in text format
            # when type is ifmap or all
            args.format = 'text'
            self.IST.get('Snh_AgentStatsReq')
            xpath = '|'.join(list(StatsMap.values()))
            self.output_formatters(args, xpath)
            self.IST.get('Snh_ShowIFMapAgentStatsReq')
            xpath = '//ShowIFMapAgentStatsResp'
            self.output_formatters(args, xpath)
        elif args.type == 'ifmap':
            self.IST.get('Snh_ShowIFMapAgentStatsReq')
            xpath = '//ShowIFMapAgentStatsResp'
            self.output_formatters(args, xpath)
        else:
            self.IST.get('Snh_AgentStatsReq')
            self.output_formatters(args, StatsMap[args.type])

    def SnhService(self, args):
        path = 'Snh_%sInfo' % args.name
        if args.pkt:
            xpath = '//%sPkt' % args.name
        else:
            xpath = '//%sStats' % args.name

        if args.name == "Metadata":
            xpath = "//MetadataResponse"

        if args.intf:
            if args.name == "Arp":
                path = "Snh_InterfaceArpStatsReq"
                xpath = "//InterfaceArpStats"
            elif args.name == "Icmpv6":
                path = "Snh_InterfaceIcmpv6StatsReq"
                xpath = "//InterfaceIcmpv6Stats"
            elif args.name == "Dns":
                path = "Snh_VmVdnsListReq"
                xpath = "//VmVdnsListEntry"
        elif args.name == "Arp":
            if args.cache:
                path = "Snh_ShowArpCache"
                xpath = "//ArpSandeshData"
            elif args.garp_cache:
                path = "Snh_ShowGratuitousArpCache"
                xpath = "//ArpSandeshData"

        if args.name == "ShowAll":
            xpath = ("//*[self::PktStats or self::DhcpStats "
                     "or self::ArpStats or self::DnsStats "
                     "or self::IcmpStats or self::MetadataResponse]")
            args.format = "text"

        self.IST.get(path)
        self.output_formatters(args, xpath)

    def SnhHealthCheck(self,args):
        self.IST.get('Snh_HealthCheckSandeshReq?uuid=' + args.uuid)

        xpath = "//HealthCheckSandeshData"
        default_columns = ["uuid", "name", "monitor_type", "http_method",
                           "url_path", "expected_codes", "delay", "timeout",
                           "max_retries"]

        self.output_formatters(args, xpath, default_columns)

    def SnhBaaS(self,args):
        self.IST.get('Snh_BgpAsAServiceSandeshReq')
        xpath = "//BgpAsAServiceSandeshList"
        self.output_formatters(args, xpath)

    def SnhShowIFMap(self, args):
        path = ('Snh_ShowIFMapAgentReq?table_name=%s&node_sub_string=%s'
                '&link_type_sub_string=%slink_node_sub_string=%s' %
                (args.table, args.node, args.link_type, args.link_node))

        self.IST.get(path)
        args.format = 'text'
        self.output_formatters(args, "//element")

class CLI_collector(CLI_basic):

    def __init__(self, parser, host, port, filename):
        CLI_basic.__init__(self, parser, host, port, filename)
        self.add_parse_args()

    def add_parse_args(self):
        subp = self.subparser.add_parser('server',
                                         parents = [self.common_parser],
                                         help='Show collector server info')
        subp.add_argument('type',
                          choices=['stats', 'generators',
                                   'table', 'stats_table'])
        subp.set_defaults(func=self.SnhShowCollectorServerReq)

        subp = self.subparser.add_parser('redis',
                                         help='Show redis server UVE info')
        subp.set_defaults(func=self.SnhRedisUVERequest)

    def SnhShowCollectorServerReq(self, args):
        path = 'Snh_ShowCollectorServerReq'
        self.IST.get(path)
        if args.type == 'stats':
            self.IST.printText("/ShowCollectorServerResp/rx_socket_stats")
            self.IST.printText("/ShowCollectorServerResp/tx_socket_stats")
            self.IST.printText("/ShowCollectorServerResp/stats")
            self.IST.printText("/ShowCollectorServerResp/cql_metrics")
            self.IST.printText("/ShowCollectorServerResp/errors/DbErrors")
        elif args.type == "generators":
            xpath = '//GeneratorSummaryInfo'
            self.output_formatters(args, xpath)
        elif args.type == "table":
            xpath = '//table_info/list/DbTableInfo'
            self.output_formatters(args, xpath)
        elif args.type == "stats_table":
            xpath = '//statistics_table_info/list/DbTableInfo'
            self.output_formatters(args, xpath)

    def SnhRedisUVERequest(self, args):
        self.IST.get('Snh_RedisUVERequest')
        self.IST.printText("//RedisUveInfo/*")

def valid_period(s):
    if (not (s[-1] in 'smhdw') and s[0:-1].isdigit()):
        msg = '''
                Invalid time period.
                format: number followed one of charactors
                (s: seconds, m: minutes, h: hours, w:weeks)
        '''
        raise argparse.ArgumentTypeError(msg)
    else:
        mapping = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800
        }
        return int(s[0:-1]) * mapping.get(s[-1], 0)

def is_ipv4(addr):
    try:
        socket.inet_pton(socket.AF_INET, addr)
    except socket.error:
        return False
    return True

def is_ipv6(addr):
    try:
        socket.inet_pton(socket.AF_INET6, addr)
    except socket.error:
        return False
    return True

def addressInNetwork(addr, prefix):
    ipaddr = struct.unpack('!L',socket.inet_aton(addr))[0]
    pure_prefix = prefix.split(':')[-1]  # strip RD info if any
    netaddr,bits = pure_prefix.split('/')
    netaddr = struct.unpack('!L',socket.inet_aton(netaddr))[0]
    netmask = ((1<<(32-int(bits))) - 1)^0xffffffff
    return ipaddr & netmask == netaddr & netmask

def addressInNetwork6(addr, prefix):
    addr_upper,addr_lower = struct.unpack(
                            '!QQ',socket.inet_pton(socket.AF_INET6, addr))
    netaddr,bits = prefix.split('/')
    net_upper,net_lower = struct.unpack(
                          '!QQ',socket.inet_pton(socket.AF_INET6, netaddr))
    if int(bits) < 65 :
        netmask = ((1<<(64-int(bits))) - 1)^0xffffffffffffffff
        return addr_upper & netmask == net_upper & netmask
    elif addr_upper != net_upper:
        return False
    else:
        netmask = ((1<<(128-int(bits))) - 1)^0xffffffffffffffff
        return addr_lower & netmask == net_lower & netmask

def validate_uuid(id):
    try:
        obj = UUID(str(id))
    except:
        return False
    return str(id)

def main():

    argv = sys.argv[1:]

    if '--version' in argv:
        print(version)
        sys.exit()

    host = os.environ.get('INTROSPECT_HOST', None)
    port = os.environ.get('INTROSPECT_PORT', None)
    global proxy
    global token
    proxy = os.environ.get('INTROSPECT_PROXY', None)
    token = os.environ.get('INTROSPECT_TOKEN', None)
    filename = None

    try:
        host = argv[argv.index('--host') + 1]
    except ValueError:
        pass

    try:
        port = argv[argv.index('--port') + 1]
    except ValueError:
        pass

    try:
        proxy = argv[argv.index('--proxy') + 1]
    except ValueError:
        pass

    try:
        token = argv[argv.index('--token') + 1]
    except ValueError:
        pass

    try:
        filename = argv[argv.index('--file') + 1]
    except ValueError:
        pass

    if filename and not os.path.isfile(filename):
        print("Failed to find " + filename)
        sys.exit(1)

    if host:
        print("Introspect Host: " + host)

    global debug
    if '--debug' in argv:
        debug = True

    parser = argparse.ArgumentParser(prog='ist',
        description='A script to make Contrail Introspect output CLI friendly.')
    parser.add_argument('--version',  action="store_true",  help="Script version")
    parser.add_argument('--debug',    action="store_true",  help="Verbose mode")
    parser.add_argument('--host',     type=str,             help="Introspect host address. Default: localhost")
    parser.add_argument('--port',     type=int,             help="Introspect port number")
    parser.add_argument('--proxy',    type=str,             help="Introspect proxy URL")
    parser.add_argument('--token',    type=str,             help="Token for introspect proxy requests")
    parser.add_argument('--file',     type=str,             help="Introspect file")

    roleparsers = parser.add_subparsers()

    for svc in sorted(ServiceMap.keys()):
        p = roleparsers.add_parser(svc, help=ServiceMap[svc])
        if 'CLI_%s' % (svc) in globals():
            globals()['CLI_%s' % (svc)](p, host, port, filename)

    args, unknown = parser.parse_known_args()
    if ("func" in args):
      args.func(args)
    else:
      parser.print_usage()

if __name__ == "__main__":
    main()
