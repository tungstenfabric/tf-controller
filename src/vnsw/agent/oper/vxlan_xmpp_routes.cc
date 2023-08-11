#include <oper/operdb_init.h>
#include <oper/route_common.h>
#include <oper/vrf.h>
#include <oper/bridge_route.h>
#include <oper/inet_unicast_route.h>
#include <oper/evpn_route.h>
#include <oper/agent_route.h>
#include <oper/vn.h>
#include <oper/vrf.h>
#include <controller/controller_route_path.h>
#include <oper/vxlan_routing_manager.h>

template<class RouteTable, class RouteEntry>
static const AgentPath *LocalVmExportInterface(Agent* agent,
    RouteTable *table, RouteEntry *route);

void VxlanRoutingManager::XmppAdvertiseEvpnRoute(const IpAddress& prefix_ip,
const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
const RouteParameters& params, const BgpPeer *bgp_peer) {
    VrfEntry* vrf = agent_->vrf_table()->FindVrfFromName(vrf_name);
    EvpnAgentRouteTable *evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>(vrf->GetEvpnRouteTable());
    if (evpn_table == NULL) {
        return;
    }

    // If route is a tunnel
    if (agent_->router_id() != params.nh_addr_.to_v4()) {
        XmppAdvertiseEvpnTunnel(evpn_table,
            prefix_ip, prefix_len, vxlan_id, vrf_name, params, bgp_peer);
        return;
    }

    // Or this is an interface
    XmppAdvertiseEvpnInterface(evpn_table,
            prefix_ip, prefix_len, vxlan_id, vrf_name, params, bgp_peer);
}

void VxlanRoutingManager::XmppAdvertiseInetRoute(const IpAddress& prefix_ip,
const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
const RouteParameters& params, const BgpPeer *bgp_peer) {
    VrfEntry* vrf = agent_->vrf_table()->FindVrfFromName(vrf_name);
    InetUnicastAgentRouteTable *inet_table =
        vrf->GetInetUnicastRouteTable(prefix_ip);
    if (inet_table == NULL) {
        return;
    }

    // If the route is a tunnel
    if (agent_->router_id() != params.nh_addr_.to_v4()) {
        XmppAdvertiseInetTunnel(inet_table,
            prefix_ip, prefix_len, vxlan_id, vrf_name, params, bgp_peer);
        return;
    }

    // If the route is an interface
    XmppAdvertiseInetInterface(inet_table,
            prefix_ip, prefix_len, vxlan_id, vrf_name, params, bgp_peer);
}

void VxlanRoutingManager::XmppAdvertiseEvpnTunnel(
    EvpnAgentRouteTable *evpn_table, const IpAddress& prefix_ip,
    const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
    const RouteParameters& params, const BgpPeer *bgp_peer
) {
    ControllerVmRoute *data =
        ControllerVmRoute::MakeControllerVmRoute(bgp_peer,
            agent_->fabric_vrf_name(),
            agent_->router_id(),
            vrf_name,
            params.nh_addr_.to_v4(),
            TunnelType::VxlanType(),
            vxlan_id,
            MacAddress(),
            params.vn_list_,
            params.sg_list_,
            params.tag_list_,
            params.path_preference_,
            false,  // ecmp_supressed (we expect that arrived route is single)
            EcmpLoadBalance(),
            false);  // item->entry.etree_leaf
    evpn_table->AddRemoteVmRouteReq(bgp_peer,
        vrf_name, MacAddress(), prefix_ip,
        prefix_len,
        0,  // ethernet tag is 0 for Type 5
        data);

    // Since external routers send route advertisement
    // only to EVPN table, then Inet table
    // should be update here manually
    if (IsExternalType5(params.nh_addresses_, agent_) == true) {
        InetUnicastAgentRouteTable *inet_table =
            evpn_table->vrf_entry()->GetInetUnicastRouteTable(prefix_ip);
        XmppAdvertiseInetTunnel(inet_table,
            prefix_ip, prefix_len, vxlan_id, vrf_name, params, bgp_peer);
    }
}

void VxlanRoutingManager::XmppAdvertiseEvpnInterface(
    EvpnAgentRouteTable *evpn_table, const IpAddress& prefix_ip,
    const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
    const RouteParameters& params, const BgpPeer *bgp_peer
) {
    EvpnRouteEntry *route = evpn_table->FindRoute(MacAddress(),
        prefix_ip, prefix_len, 0);
    if (RoutePrefixIsEqualTo(route, prefix_ip, prefix_len) == false) {
        return;
    }
    const AgentPath * path =
        LocalVmExportInterface(agent_, evpn_table, route);

    CopyInterfacePathToEvpnTable(path,
        prefix_ip,
        prefix_len,
        bgp_peer,
        RouteParameters(IpAddress(),  // NH address, not needed here
            params.vn_list_,
            params.sg_list_,
            params.communities_,
            params.tag_list_,
            params.path_preference_,
            params.ecmp_load_balance_,
            params.sequence_number_),
        evpn_table);
}

void VxlanRoutingManager::XmppAdvertiseInetTunnel(
    InetUnicastAgentRouteTable *inet_table, const IpAddress& prefix_ip,
    const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
    const RouteParameters& params, const BgpPeer *bgp_peer) {
    ControllerVmRoute *data =
        ControllerVmRoute::MakeControllerVmRoute(bgp_peer,
            agent_->fabric_vrf_name(),
            agent_->router_id(),
            vrf_name,
            params.nh_addr_.to_v4(),
            TunnelType::VxlanType(),
            vxlan_id,
            MacAddress(),
            params.vn_list_,
            params.sg_list_,
            params.tag_list_,
            params.path_preference_,
            false,
            params.ecmp_load_balance_,
            false);
    inet_table->AddRemoteVmRouteReq(bgp_peer, vrf_name, prefix_ip,
                                    prefix_len, data);
}

void VxlanRoutingManager::XmppAdvertiseInetInterface(
    InetUnicastAgentRouteTable *inet_table, const IpAddress& prefix_ip,
    const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
    const RouteParameters& params, const BgpPeer *bgp_peer) {

    VrfEntry *vrf = inet_table->vrf_entry();
    InetUnicastRouteEntry local_vm_route_key(
        vrf, prefix_ip, prefix_len, false);
    InetUnicastRouteEntry *local_vm_route =
        dynamic_cast<InetUnicastRouteEntry *>
        (inet_table->FindLPM(local_vm_route_key));
    if (RoutePrefixIsEqualTo(local_vm_route, prefix_ip, prefix_len) == false) {
        return;
    }

    const AgentPath *path =
        LocalVmExportInterface(agent_, inet_table, local_vm_route);

    CopyInterfacePathToInetTable(path,
        prefix_ip,
        prefix_len,
        bgp_peer,
        params,
        inet_table);
}

template<class RouteTable, class RouteEntry>
static const AgentPath *LocalVmExportInterface(Agent* agent,
    RouteTable *table, RouteEntry *route) {
    if (table == NULL || agent == NULL || route == NULL) {
        return NULL;
    }

    const AgentPath *tm_path = NULL;
    const AgentPath *rt_path = NULL;

    for (Route::PathList::const_iterator it =
        route->GetPathList().begin();
        it != route->GetPathList().end(); it++) {
        tm_path =
            static_cast<const AgentPath *>(it.operator->());
        if (tm_path == NULL || tm_path->peer() == NULL) {
            continue;
        }
        if (tm_path->peer()->GetType() ==
            agent->local_vm_export_peer()->GetType()) {
            if (tm_path->nexthop() &&
                tm_path->nexthop()->GetType() == NextHop::INTERFACE) {
                rt_path = tm_path;
            } else if (tm_path->nexthop() &&
                tm_path->nexthop()->GetType() == NextHop::COMPOSITE) {
                return tm_path;
            }
        }
    }
    return rt_path;
}

//
//END-OF-FILE
//

