#include <boost/uuid/uuid_io.hpp>
#include <boost/lexical_cast.hpp>
#include <cmn/agent_cmn.h>

#include <base/logging.h>
#include <oper/operdb_init.h>
#include <oper/route_common.h>
#include <oper/vrf.h>
#include <oper/bridge_route.h>
#include <oper/inet_unicast_route.h>
#include <oper/evpn_route.h>
#include <oper/agent_route.h>
#include <oper/agent_route_walker.h>
#include <oper/vn.h>
#include <oper/vrf.h>
#include <oper/vxlan_routing_manager.h>
#include <oper/tunnel_nh.h> //for tunnel interception

uint32_t VxlanRoutingManager::loc_sequence_ = 0;

tbb::mutex VxlanRoutingManager::mutex_;

/*
 *
 * Routes Leaking
 *
 */

bool VxlanRoutingManager::RouteNotify(DBTablePartBase *partition,
                                      DBEntryBase *e) {
    const InetUnicastRouteEntry *inet_rt =
        dynamic_cast<const InetUnicastRouteEntry*>(e);
    if (inet_rt) {
        if (IsBridgeVrf(inet_rt->vrf())) {
            return InetRouteNotify(partition, e);
        }
        // // Deactive redundant bgp paths by moving local peer
        // // path to top
        // if (IsRoutingVrf(inet_rt->vrf())) {
        //     const AgentPath * loc_vm_port =
        //         FindInterfacePathWithGivenPeer(inet_rt,
        //         routing_vrf_interface_peer_->GetType(), true);
        //     if (loc_vm_port) {
        //         Route::PathList & path_list =
        //             const_cast<Route::PathList &>(inet_rt->GetPathList());
        //         path_list.reverse();
        //     }
        // }
    }

    const EvpnRouteEntry *evpn_rt =
        dynamic_cast<const EvpnRouteEntry *>(e);
    if (evpn_rt && IsRoutingVrf(evpn_rt->vrf())) {
        return EvpnRouteNotify(partition, e);
    }
    return true;
}

/*
 *
 * 
 * Step 1. InetRouteNotify
 * Handles changes in inet routes originating from a bridge VRF.
 * Copies new routes to the routing VRF EVPN Type 5 table.
 * Or deletes old routes from the routing VRF EVPN Type 5 table.
 * 
 * 
 */
//Handles change in NH of local vm port path
//For all host routes with non local vm port path, evpn route in routing vrf
//need not be added. It should come from CN.
bool VxlanRoutingManager::InetRouteNotify(DBTablePartBase *partition,
                                          DBEntryBase *e) {
    const InetUnicastRouteEntry *inet_rt =
        dynamic_cast<const InetUnicastRouteEntry*>(e);

    if (inet_rt->addr().is_v6() &&
        inet_rt->addr().to_v6().is_link_local()) {
        return true;
    }

    const VrfEntry *routing_vrf =
        vrf_mapper_.GetRoutingVrfUsingAgentRoute(inet_rt);
    if (routing_vrf == NULL || routing_vrf == inet_rt->vrf()) {
        return true;
    }

    EvpnAgentRouteTable *evpn_table =
        dynamic_cast<EvpnAgentRouteTable *>(routing_vrf->GetEvpnRouteTable());
    if (evpn_table == NULL) {
        return true;
    }
    
    const AgentPath *local_vm_port_path = NULL;
    local_vm_port_path = inet_rt->FindIntfOrCompLocalVmPortPath();

    if (local_vm_port_path == NULL) {
        // If BGPaaS path with interface (or interface/mixed composite) is
        // found, then it is extracted and copied into EVPN Type5 table
        local_vm_port_path = FindBGPaaSPath(inet_rt);
        if (local_vm_port_path != NULL) {
            AdvertiseBGPaaSRoute(inet_rt->addr(), inet_rt->plen(),
                local_vm_port_path, evpn_table);
            return true;
        }
    }

    // if path with LOCAL_VM_PORT hasn't been found, then
    // this probably may mean that it was deleted
    if (local_vm_port_path == NULL) {
        ClearRedundantVrfPath(e);
        WhenBridgeInetIntfWasDeleted(inet_rt, routing_vrf);
        return true;
    }

    PathPreference preference = local_vm_port_path->path_preference();
    preference.set_loc_sequence(GetNewLocalSequence());
    // preference.set_preference(100);
    VnListType dest_vns;
    dest_vns.insert(routing_vrf->vn()->GetName());

    CopyInterfacePathToEvpnTable(local_vm_port_path,
        inet_rt->addr(),
        inet_rt->plen(),
        routing_vrf_interface_peer_,  // agent->local_vm_export_peer(),
        RouteParameters(IpAddress(),  // not needed here
            MacAddress(),             // not needed here ?
            dest_vns,
            local_vm_port_path->sg_list(),
            local_vm_port_path->communities(),
            local_vm_port_path->tag_list(),
            preference,
            local_vm_port_path->ecmp_load_balance(),
            routing_vrf_interface_peer_->sequence_number()),
        evpn_table);

    return true;
}

/*
 * Step 2.
 * Copies a route from the routing VRF EVPN Type 5 table into the
 * routing VRF Inet table.
 *  
 */
bool VxlanRoutingManager::EvpnRouteNotify(DBTablePartBase *partition,
                                          DBEntryBase *e) {
    const EvpnRouteEntry *evpn_rt =
        dynamic_cast<const EvpnRouteEntry *>(e);

    if (evpn_rt->IsType5() == false) {
        return true;
    }

    VrfEntry *vrf = evpn_rt->vrf();
    const AgentPath *local_vm_port_path = evpn_rt->FindPath(
        routing_vrf_interface_peer_);

    const AgentPath *bgp_path =
        FindPathWithGivenPeer(evpn_rt, Peer::BGP_PEER);

    if (bgp_path) {
        XmppAdvertiseInetRoute(evpn_rt->ip_addr(),
            evpn_rt->GetVmIpPlen(), vrf->GetName(), bgp_path);
    }

    if (local_vm_port_path) {
        const NextHop *anh = local_vm_port_path->nexthop();
        if (anh == NULL) {
            return true;
        }
        CopyPathToInetTable(local_vm_port_path,
            evpn_rt->ip_addr(),
            evpn_rt->GetVmIpPlen(),
            routing_vrf_interface_peer_,
                RouteParameters(IpAddress(),
                MacAddress(),
                local_vm_port_path->dest_vn_list(),
                local_vm_port_path->sg_list(),
                local_vm_port_path->communities(),
                local_vm_port_path->tag_list(),
                local_vm_port_path->path_preference(),
                local_vm_port_path->ecmp_load_balance(),
                routing_vrf_interface_peer_->sequence_number()),
            vrf->GetInetUnicastRouteTable(evpn_rt->ip_addr()));

        LeakRoutesIntoBridgeTables(partition,
            e, vrf->vn()->logical_router_uuid(), NULL, true);
    }

    if (bgp_path == NULL) {
        // the route might be deleted
        WhenRoutingEvpnRouteWasDeleted(evpn_rt,
            routing_vrf_vxlan_bgp_peer_);
    }

    if (local_vm_port_path == NULL) {
        // the route might be deleted
        WhenRoutingEvpnRouteWasDeleted(evpn_rt,
            routing_vrf_interface_peer_);
        // and/or it requires publishing in bridge
        LeakRoutesIntoBridgeTables(partition, e,
           vrf->vn()->logical_router_uuid(), NULL, true);
        return true;
    }

    return true;
}

/*
 *
 * Routes Deletion
 *
 */
void VxlanRoutingManager::ClearRedundantVrfPath(DBEntryBase *e) {
    InetUnicastRouteEntry *inet_route =
        dynamic_cast<InetUnicastRouteEntry*>(e);
    if (inet_route == NULL) {
        return;
    }
    if (inet_route->GetPathList().size() > 1 &&
        inet_route->FindPath(agent_->evpn_routing_peer())) {
        InetUnicastAgentRouteTable::Delete(agent_->evpn_routing_peer(),
            inet_route->vrf()->GetName(),
            inet_route->addr(),
            inet_route->plen());
    }
}

/*
 *
 * Step 1. If a route is deleted / changed in a bridge VRF INET,
 * then schedule deletion of a route / path in a routing VRF EVPN
 * Type 5.
 * 
 */

void VxlanRoutingManager::WhenBridgeInetIntfWasDeleted(
    const InetUnicastRouteEntry *inet_rt,
    const VrfEntry* routing_vrf) {

    if (inet_rt->FindPath(agent_->evpn_routing_peer())) {
        return;
    }

    // Check that this route is present in the routing VRF
    const EvpnAgentRouteTable *evpn_table =
        dynamic_cast<const EvpnAgentRouteTable *>
        (routing_vrf->GetEvpnRouteTable());
    if (evpn_table == NULL) {
        return;
    }

    const EvpnRouteEntry *evpn_rt =
        const_cast<EvpnAgentRouteTable *>
        (evpn_table)->FindRoute(MacAddress(),
        inet_rt->addr(), inet_rt->plen(), 0);
    if (RoutePrefixIsEqualTo(evpn_rt, inet_rt->addr(), inet_rt->plen()) == false) {
        if (inet_rt->IsDeleted()) {
            // That might be an IPAM route from neighb. bridge VRF instances.
            if (IsHostRoute(inet_rt->addr(), inet_rt->plen()) == false) {
                DeleteIpamRoutes(inet_rt->vrf()->vn(),
                    inet_rt->vrf()->GetName(),
                    inet_rt->addr(), inet_rt->plen());
            }
        }
        return;
    }

    bool ok_to_delete = inet_rt->IsDeleted() ||
        evpn_rt->FindPath(routing_vrf_interface_peer_);
    if (ok_to_delete) {
        // Delete EVPN Type 5 record in the routing VRF
        EvpnAgentRouteTable::DeleteReq(
            routing_vrf_interface_peer_,
            routing_vrf->GetName(),
            MacAddress(),
            inet_rt->addr(),
            inet_rt->plen(),
            0,  // ethernet_tag = 0 for Type5
            NULL);
    }
}

/*
 *
 * Step 2. Delete the routing VRF Inet route
 * 
 */
void VxlanRoutingManager::WhenRoutingEvpnRouteWasDeleted
    (const EvpnRouteEntry *routing_evpn_rt, const Peer *delete_from_peer) {

    if (routing_evpn_rt->FindPath(agent_->evpn_routing_peer())) {
        // Actually, VRF NH Routes are not allowed here
        return;
    }

    VrfEntry *vrf = routing_evpn_rt->vrf();
    if (vrf == NULL) {
        return;
    }
    InetUnicastAgentRouteTable *routing_inet_table =
        vrf->GetInetUnicastRouteTable(routing_evpn_rt->ip_addr());
    if (routing_inet_table == NULL) {
        return;
    }

    // check that the Inet table holds the corresponding route
    InetUnicastRouteEntry local_vm_route_key(
        routing_inet_table->vrf_entry(),
        routing_evpn_rt->ip_addr(),
        routing_evpn_rt->GetVmIpPlen(), false);
    InetUnicastRouteEntry *inet_rt =
        dynamic_cast<InetUnicastRouteEntry *>
        (routing_inet_table->FindLPM(local_vm_route_key));
    if (RoutePrefixIsEqualTo(inet_rt, routing_evpn_rt->ip_addr(),
        routing_evpn_rt->GetVmIpPlen()) == false) {
        return;
    }

    bool ok_to_delete = routing_evpn_rt->IsDeleted() ||
        inet_rt->FindPath(delete_from_peer);

    if (ok_to_delete) {
        // Delete EVPN Type 5 record in the routing VRF
        InetUnicastAgentRouteTable::DeleteReq(
            delete_from_peer,
            vrf->GetName(),
            routing_evpn_rt->ip_addr(),
            routing_evpn_rt->GetVmIpPlen(),
            NULL);
    }
}

bool VxlanRoutingManager::WithdrawEvpnRouteFromRoutingVrf
(DBTablePartBase *partition, DBEntryBase *e) {
    EvpnRouteEntry *evpn_rt = dynamic_cast<EvpnRouteEntry *>(e);
    if (!evpn_rt || (evpn_rt->vrf()->vn() == NULL) || (!evpn_rt->IsType5()))
        return true;

    // Remove deleted EVPN Type 5 record in the routing VRF
    EvpnAgentRouteTable::DeleteReq(
        routing_vrf_interface_peer_,
        evpn_rt->vrf()->GetName(),
        MacAddress(),
        evpn_rt->ip_addr(),
        evpn_rt->GetVmIpPlen(),
        0,  // ethernet_tag = 0 for Type5
        NULL);

    // const VrfEntry *del_bridge_vrf = vn->GetVrf();
    // InetUnicastAgentRouteTable *deleted_vn_inet_table =
    //         del_bridge_vrf->GetInetUnicastRouteTable(evpn_rt->ip_addr());
    // deleted_vn_inet_table->Delete(agent_->evpn_routing_peer(),
    //                       del_bridge_vrf->GetName(),
    //                       evpn_rt->ip_addr(),
    //                       evpn_rt->GetVmIpPlen());
    return true;
}

bool VxlanRoutingManager::LeakRoutesIntoBridgeTables
(DBTablePartBase *partition, DBEntryBase *e, const boost::uuids::uuid &uuid,
 const VnEntry *vn, bool update) {

    EvpnRouteEntry *evpn_rt = dynamic_cast<EvpnRouteEntry *>(e);
    if (!evpn_rt || (evpn_rt->vrf()->vn() == NULL) || (!evpn_rt->IsType5()))
        return true;
    if (uuid == boost::uuids::nil_uuid())
        return true;
    // Only non-local non-/32 and non-/128 routes are
    // copied to bridge vrfs
    if (IsHostRouteFromLocalSubnet(evpn_rt)) { //IsLocalSubnetHostRoute
        return true;
    }

    VxlanRoutingVrfMapper::RoutedVrfInfo &lr_vrf_info =
        vrf_mapper_.lr_vrf_info_map_[uuid];
    VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnList update_bridge_vn_list;
    VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter it;
    if (update && vn != NULL) {
        update_bridge_vn_list.insert(vn);
        it = update_bridge_vn_list.find(vn);
    } else {
        update_bridge_vn_list = lr_vrf_info.bridge_vn_list_;
        it = update_bridge_vn_list.begin();
    }
    while (it != update_bridge_vn_list.end()) {
        VrfEntry *bridge_vrf =  (*it)->GetVrf();

        if (bridge_vrf == NULL) {
            it++;
            continue;
        }

        if (IsVrfLocalRoute(evpn_rt, bridge_vrf)) {
            it++;
            continue;
        }

        InetUnicastAgentRouteTable *inet_table =
                bridge_vrf->GetInetUnicastRouteTable(evpn_rt->ip_addr());

        if (evpn_rt->IsDeleted()) {
            InetUnicastAgentRouteTable::DeleteReq(agent_->evpn_routing_peer(),
                              bridge_vrf->GetName(),
                              evpn_rt->ip_addr(),
                              evpn_rt->GetVmIpPlen(),
                              NULL);
        } else {
            const AgentPath *p = evpn_rt->GetActivePath();
            const VrfEntry *routing_vrf = lr_vrf_info.routing_vrf_;
            // Now all interface routes in routing vrf have BGP_PEER copies
            if (routing_vrf == NULL) {
                return true;
            }

            DBRequest nh_req(DBRequest::DB_ENTRY_ADD_CHANGE);
            nh_req.key.reset(new VrfNHKey(routing_vrf->GetName(), false, false));
            nh_req.data.reset(new VrfNHData(false, false, false));
            inet_table->AddEvpnRoutingRoute(evpn_rt->ip_addr(),
                                    evpn_rt->GetVmIpPlen(),
                                    bridge_vrf,
                                    agent_->evpn_routing_peer(),
                                    p->sg_list(),
                                    p->communities(),
                                    p->path_preference(),
                                    p->ecmp_load_balance(),
                                    p->tag_list(),
                                    nh_req,
                                    routing_vrf->vxlan_id(),
                                    p->dest_vn_list());
        }
        it++;
    }
    return true;
}

//
//END-OF-FILE
//

