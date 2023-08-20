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
#include <oper/tunnel_nh.h>

template<class RouteTable, class RouteEntry>
static const AgentPath *LocalVmExportInterface(Agent* agent,
    RouteTable *table, RouteEntry *route);

TunnelNHKey* VxlanRoutingManager::AllocateTunnelNextHopKey(
    const IpAddress& dip, const MacAddress& dmac) const {

    const Ip4Address rtr_dip = dip.to_v4();

    const std::vector<IpAddress> nh_addresses(1, dip);
    bool is_ext_type5 = IsExternalType5(nh_addresses, agent_);
    bool is_zero_mac = dmac.IsZero();

    MacAddress rtr_dmac;
    if (is_ext_type5 && !is_zero_mac) {
        rtr_dmac = dmac;
    } else {
        rtr_dmac = NbComputeMac(rtr_dip, agent_);
    }

    TunnelNHKey *tun_nh_key = new TunnelNHKey(agent_->fabric_vrf_name(),
        agent_->router_id(),
        rtr_dip,
        false,
        TunnelType(TunnelType::VXLAN),
        rtr_dmac);
    return tun_nh_key;
}

void VxlanRoutingManager::XmppAdvertiseEvpnRoute(const IpAddress& prefix_ip,
const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
const RouteParameters& params, const Peer *bgp_peer) {
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
    const int prefix_len, const std::string vrf_name,
    const AgentPath* path) {

    VrfEntry* vrf = agent_->vrf_table()->FindVrfFromName(vrf_name);
    InetUnicastAgentRouteTable *inet_table =
        vrf->GetInetUnicastRouteTable(prefix_ip);

    if (path->nexthop() && path->nexthop()->GetType() ==
        NextHop::TUNNEL) {
            XmppAdvertiseInetTunnel(inet_table,
                prefix_ip, prefix_len, vrf_name, path);
        return;
    }

    if (path->nexthop() &&
        (path->nexthop()->GetType() == NextHop::INTERFACE ||
        path->nexthop()->GetType() == NextHop::COMPOSITE)) {
        XmppAdvertiseInetInterfaceOrComposite(inet_table,
            prefix_ip, prefix_len, vrf_name, path);
    }
}

void VxlanRoutingManager::XmppAdvertiseEvpnTunnel(
    EvpnAgentRouteTable *evpn_table, const IpAddress& prefix_ip,
    const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
    const RouteParameters& params, const Peer *peer
) {
    const BgpPeer *bgp_peer = dynamic_cast<const BgpPeer*>(peer);
    if (bgp_peer == NULL) {
        return;
    }
    DBRequest nh_req(DBRequest::DB_ENTRY_ADD_CHANGE);
    std::auto_ptr<TunnelNHKey> tun_nh_key (AllocateTunnelNextHopKey(
        params.nh_addr_, params.nh_mac_));

    ControllerVmRoute *data =
        ControllerVmRoute::MakeControllerVmRoute(dynamic_cast<const BgpPeer*>(bgp_peer),
        agent_->fabric_vrf_name(),
        agent_->router_id(),
        vrf_name,
        tun_nh_key->dip(),
        TunnelType::VxlanType(),
        vxlan_id,
        tun_nh_key->rewrite_dmac(),
        params.vn_list_,
        params.sg_list_,
        params.tag_list_,
        params.path_preference_,
        true,
        EcmpLoadBalance(),
        false);
    evpn_table->AddRemoteVmRouteReq(bgp_peer,
        vrf_name,
        MacAddress(),
        prefix_ip,
        prefix_len,
        0,  // ethernet_tag is zero for Type5
        data);
}

void VxlanRoutingManager::XmppAdvertiseEvpnInterface(
    EvpnAgentRouteTable *evpn_table, const IpAddress& prefix_ip,
    const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
    const RouteParameters& params, const Peer *bgp_peer
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
            MacAddress(),
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
        const int prefix_len, const std::string vrf_name,
        const AgentPath* path) {

    DBRequest nh_req(DBRequest::DB_ENTRY_ADD_CHANGE);
    TunnelNH *tun_nh = dynamic_cast<TunnelNH*>(path->nexthop());

    TunnelNHKey *tun_nh_key = AllocateTunnelNextHopKey(*(tun_nh->GetDip()),
        tun_nh->rewrite_dmac());
    std::string origin_vn = "";

    nh_req.key.reset(tun_nh_key);
    nh_req.data.reset(new TunnelNHData);

    inet_table->AddEvpnRoutingRoute(prefix_ip,
        prefix_len,
        inet_table->vrf_entry(),
        routing_vrf_vxlan_bgp_peer_,
        path->sg_list(),
        path->communities(),
        path->path_preference(),
        path->ecmp_load_balance(),
        path->tag_list(),
        nh_req,
        path->vxlan_id(),
        path->dest_vn_list(),
        origin_vn);
}

void VxlanRoutingManager::XmppAdvertiseInetInterfaceOrComposite(
        InetUnicastAgentRouteTable *inet_table, const IpAddress& prefix_ip,
        const int prefix_len, const std::string vrf_name,
        const AgentPath* path) {

    CopyPathToInetTable(path,
        prefix_ip,
        prefix_len,
        routing_vrf_vxlan_bgp_peer_,
        RouteParameters(IpAddress(),
            MacAddress(),
            path->dest_vn_list(),
            path->sg_list(),
            path->communities(),
            path->tag_list(),
            path->path_preference(),
            path->ecmp_load_balance(),
            path->peer_sequence_number()),
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

