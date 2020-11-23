#include <cmn/agent_cmn.h>
#include <route/route.h>
#include <oper/nexthop.h>
#include <oper/tunnel_nh.h>
#include <oper/route_common.h>
#include <oper/vrf.h>
#include <oper/vrouter.h>
#include <oper/route_leak.h>

void RouteLeakState::AddIndirectRoute(const AgentRoute *route) {
    const InetUnicastRouteEntry *uc_rt =
        static_cast<const InetUnicastRouteEntry *>(route);
    InetUnicastAgentRouteTable *table = NULL;
    if (uc_rt->GetTableType() == Agent::INET4_UNICAST) {
        table = dest_vrf_->GetInet4UnicastRouteTable();
    } else if (uc_rt->GetTableType() == Agent::INET6_UNICAST) {
        table = dest_vrf_->GetInet6UnicastRouteTable();
    }
    const AgentPath *active_path = uc_rt->GetActivePath();
    const TunnelNH *nh = dynamic_cast<const TunnelNH *>(active_path->nexthop());

    if (nh == NULL) {
        return;
    }

    IpAddress gw_ip = *(nh->GetDip());

    if (gw_ip.is_v4() && (gw_ip.to_v4() == uc_rt->addr().to_v4()) &&
        InetUnicastAgentRouteTable::FindResolveRoute(dest_vrf_->GetName(),
                                                     uc_rt->addr().to_v4())) {
        bool resolved = false;
        MacAddress mac;
        const Interface *itf = agent_->vhost_interface();
        ArpNHKey nh_key(dest_vrf_->GetName(), uc_rt->addr().to_v4(), false);
        ArpNH *arp_nh = static_cast<ArpNH *>(agent_->nexthop_table()->
                                             FindActiveEntry(&nh_key));
        if (arp_nh) {
            resolved = arp_nh->GetResolveState();
            mac = arp_nh->GetMac();
            itf = arp_nh->GetInterface();
        }
        InetUnicastAgentRouteTable::CheckAndAddArpRoute
            (dest_vrf_->GetName(), uc_rt->addr().to_v4(), mac, itf,
             resolved, active_path->dest_vn_list(),
             active_path->sg_list(), active_path->tag_list());
        return;
    } else if (gw_ip.is_v6() && (gw_ip.to_v6() == uc_rt->addr().to_v6()) &&
        InetUnicastAgentRouteTable::FindResolveRoute(dest_vrf_->GetName(),
                                                     uc_rt->addr().to_v6())) {
        bool resolved = false;
        MacAddress mac;
        const Interface *itf = agent_->vhost_interface();
        NdpNHKey nh_key(dest_vrf_->GetName(), uc_rt->addr().to_v6(), false);
        NdpNH *ndp_nh = static_cast<NdpNH *>(agent_->nexthop_table()->
                                             FindActiveEntry(&nh_key));
        if (ndp_nh) {
            resolved = ndp_nh->GetResolveState();
            mac = ndp_nh->GetMac();
            itf = ndp_nh->GetInterface();
        }
        InetUnicastAgentRouteTable::CheckAndAddNdpRoute
            (dest_vrf_->GetName(), uc_rt->addr().to_v6(), mac, itf,
             resolved, active_path->dest_vn_list(),
             active_path->sg_list(), active_path->tag_list());
        return;
    }

    const Peer *peer = agent_->local_peer();
    peer_list_.insert(peer);

    if (gw_ip.is_v4()) {
        if (gw_ip.to_v4() == uc_rt->addr().to_v4()) {
            gw_ip = agent_->vhost_default_gateway();
        }

        table->AddGatewayRoute(peer, dest_vrf_->GetName(),
                           uc_rt->addr().to_v4(),
                           uc_rt->plen(),
                           gw_ip.to_v4(),
                           active_path->dest_vn_list(),
                           MplsTable::kInvalidExportLabel,
                           active_path->sg_list(),
                           active_path->tag_list(),
                           active_path->communities(), true);
    } else if (gw_ip.is_v6()) {
        if (gw_ip.to_v6() == uc_rt->addr().to_v6()) {
            gw_ip = agent_->vhost_default_gateway6();
        }

        table->AddGatewayRoute6(peer, dest_vrf_->GetName(),
                           uc_rt->addr().to_v6(),
                           uc_rt->plen(),
                           gw_ip.to_v6(),
                           active_path->dest_vn_list(),
                           MplsTable::kInvalidExportLabel,
                           active_path->sg_list(),
                           active_path->tag_list(),
                           active_path->communities(), true);
    } else {
        assert(0);
    }
}

void RouteLeakState::AddInterfaceRoute(const AgentRoute *route,
                                       const AgentPath *path) {
    const InetUnicastRouteEntry *uc_rt =
        static_cast<const InetUnicastRouteEntry *>(route);
    const AgentPath *active_path = path;

    if (active_path == NULL) {
        active_path = uc_rt->GetActivePath();
    }

    InterfaceNH *intf_nh = dynamic_cast<InterfaceNH *>(active_path->nexthop());
    if (intf_nh == NULL) {
        return;
    }

    if (uc_rt->IsHostRoute() &&
        ((uc_rt->addr() == agent_->router_id()) ||
         (uc_rt->addr() == agent_->router_id6()))) {
        //Dont overwrite vhost IP in default VRF
        if (intf_nh->GetInterface() != agent_->vhost_interface()) {
            return;
        }
    }

    if (intf_nh->GetInterface()->type() == Interface::PACKET) {
        peer_list_.insert(agent_->local_peer());
        InetUnicastAgentRouteTable *table = NULL;
        if (route->GetTableType() == Agent::INET4_UNICAST) {
            table = static_cast<InetUnicastAgentRouteTable *>
                            (dest_vrf_->GetInet4UnicastRouteTable());
        } else if (route->GetTableType() == Agent::INET6_UNICAST) {
            table = static_cast<InetUnicastAgentRouteTable *>
                            (dest_vrf_->GetInet6UnicastRouteTable());
        }

        table->AddHostRoute(dest_vrf_->GetName(), uc_rt->addr(), uc_rt->plen(),
                            "", true);
        return;
    }

    if (intf_nh->GetInterface()->type() == Interface::VM_INTERFACE) {
        const VmInterface *vm_intf =
            static_cast<const VmInterface *>(intf_nh->GetInterface());
        if (vm_intf->vmi_type() == VmInterface::VHOST) {
            if (uc_rt->addr() == agent_->router_id()) {
                if (uc_rt->FindLocalVmPortPath() == NULL) {
                    peer_list_.insert(agent_->local_peer());
                } else {
                    peer_list_.insert(agent_->fabric_rt_export_peer());
                }
                AddReceiveRoute(route);
                return;
            } else if (uc_rt->addr() == agent_->router_id6()) {
                if (uc_rt->FindLocalVmPortPath() == NULL) {
                    peer_list_.insert(agent_->local_peer());
                } else {
                    peer_list_.insert(agent_->fabric_rt_export_peer());
                }
                AddReceiveRoute(route);
                return;
            }
        }
    }

    const Peer *peer = active_path->peer();
    if (uc_rt->FindLocalVmPortPath() == NULL) {
        peer = agent_->local_peer();
    }

    /* Don't export /32 routes on fabric-vrf, if they are part of vrouter's
     * subnet list. To disable export, use local_peer */
    if ((uc_rt->IsHostRoute()) &&
        dest_vrf_->GetName() == agent_->fabric_vrf_name()) {
        if (agent_->oper_db()->vrouter()->IsSubnetMember(uc_rt->addr())) {
            peer = agent_->local_peer();
        }
    }

    peer_list_.insert(peer);
    VmInterfaceKey intf_key(AgentKey::ADD_DEL_CHANGE, intf_nh->GetIfUuid(),
            intf_nh->GetInterface()->name());
    LocalVmRoute *local_vm_route = NULL;
    uint8_t flags = InterfaceNHFlags::INET4;
    if (uc_rt->addr().is_v6()) {
        flags = InterfaceNHFlags::INET6;
    }
    local_vm_route =
        new LocalVmRoute(intf_key, MplsTable::kInvalidExportLabel,
                         VxLanTable::kInvalidvxlan_id, false,
                         active_path->dest_vn_list(), flags,
                         SecurityGroupList(),
                         TagList(),
                         CommunityList(),
                         active_path->path_preference(),
                         Ip4Address(0), EcmpLoadBalance(),
                         false, false, peer->sequence_number(),
                         false, true);
    local_vm_route->set_native_vrf_id(uc_rt->vrf()->rd());

    DBRequest req(DBRequest::DB_ENTRY_ADD_CHANGE);
    req.key.reset(new InetUnicastRouteKey(peer, dest_vrf_->GetName(),
                                          uc_rt->addr(), uc_rt->plen()));
    req.data.reset(local_vm_route);

    AgentRouteTable *table = NULL;
    if (uc_rt->addr().is_v4()) {
        table = agent_->vrf_table()->GetInet4UnicastRouteTable(dest_vrf_->GetName());
    } else if (uc_rt->addr().is_v6()) {
        table = agent_->vrf_table()->GetInet6UnicastRouteTable(dest_vrf_->GetName());
    } else {
        assert(0);
    }
    if (table) {
        table->Process(req);
    }
}

void RouteLeakState::AddCompositeRoute(const AgentRoute *route) {
    for(Route::PathList::const_iterator it = route->GetPathList().begin();
        it != route->GetPathList().end(); it++) {
        const AgentPath *path = static_cast<const AgentPath *>(it.operator->());
        if (path->peer()->GetType() == Peer::LOCAL_VM_PORT_PEER) {
            AddInterfaceRoute(route, path);
        }
    }
}

void RouteLeakState::AddReceiveRoute(const AgentRoute *route) {
    const InetUnicastRouteEntry *uc_rt =
        static_cast<const InetUnicastRouteEntry *>(route);
    const AgentPath *active_path = uc_rt->GetActivePath();

    /* This is a defensive check added to prevent the code below from casting NHs
     * not containing an interface to RECEIVE NH */
    const NextHop* nh = active_path->nexthop();
    if ((nh->GetType() != NextHop::INTERFACE) &&
        (nh->GetType() != NextHop::RECEIVE)) {
        return;
    }

    const ReceiveNH *rch_nh =
        static_cast<const ReceiveNH*>(active_path->nexthop());
    const VmInterface *vm_intf =
        static_cast<const VmInterface *>(rch_nh->GetInterface());

    InetUnicastAgentRouteTable *table = NULL;
    if (route->GetTableType() == Agent::INET4_UNICAST) {
        table = static_cast<InetUnicastAgentRouteTable *>(
                    dest_vrf_->GetInet4UnicastRouteTable());
    } else if (route->GetTableType() == Agent::INET6_UNICAST) {
        table = static_cast<InetUnicastAgentRouteTable *>(
                    dest_vrf_->GetInet6UnicastRouteTable());
    } else {
        assert(0);
    }

    VmInterfaceKey vmi_key(AgentKey::ADD_DEL_CHANGE, vm_intf->GetUuid(),
                           vm_intf->name());
    table->AddVHostRecvRoute(agent_->fabric_rt_export_peer(),
                             dest_vrf_->GetName(),
                             vmi_key,
                             uc_rt->addr(),
                             uc_rt->plen(),
                             agent_->fabric_vn_name(), false, true);
}

bool RouteLeakState::CanAdd(const InetUnicastRouteEntry *rt) {
    InetUnicastAgentRouteTable *table = NULL;
    if (rt->GetTableType() == Agent::INET4_UNICAST) {
        table = agent_->fabric_vrf()->GetInet4UnicastRouteTable();
    } else if (rt->GetTableType() == Agent::INET6_UNICAST) {
        table = agent_->fabric_vrf()->GetInet6UnicastRouteTable();
    }

    //Never replace resolve route and default route

    if (rt->addr().is_v4() && (rt->addr() == Ip4Address(0)) && (rt->plen() == 0)) {
        return false;
    }

    if (rt->addr().is_v6() && (rt->addr() == Ip6Address()) && (rt->plen() == 0)) {
        return false;
    }

    InetUnicastRouteEntry *rsl_rt = table->FindResolveRoute(rt->addr());
    if (rsl_rt && rt->addr() == rsl_rt->addr() &&
        rt->plen() == rsl_rt->plen()) {
        //Dont overwrite resolve route
        return false;
    }

    if (rt->IsHostRoute() &&
        ((rt->addr().is_v4() && (rt->addr() == agent_->vhost_default_gateway())) ||
         (rt->addr().is_v6() && (rt->addr() == agent_->vhost_default_gateway6())))) {
        return false;
    }

    //Always add gateway and DNS routes
    const InterfaceNH *nh =
        dynamic_cast<const InterfaceNH *>(rt->GetActiveNextHop());
    if (nh && nh->GetInterface()->type() == Interface::PACKET) {
        return true;
    }

    if ((rt->GetActivePath()->tunnel_bmap() & TunnelType::NativeType()) == 0) {
        return false;
    }

    return true;
}

void RouteLeakState::AddRoute(const AgentRoute *route) {
    const InetUnicastRouteEntry *uc_rt =
        static_cast<const InetUnicastRouteEntry *>(route);

    if (CanAdd(uc_rt) == false) {
        DeleteRoute(route, peer_list_);
        return;
    }

    std::set<const Peer *> old_peer_list = peer_list_;
    peer_list_.clear();

    if (uc_rt->GetActiveNextHop()->GetType() == NextHop::TUNNEL) {
        AddIndirectRoute(route);
    } else if ((uc_rt->GetActiveNextHop()->GetType() == NextHop::COMPOSITE)||
            (route->FindLocalVmPortPath() &&
             route->FindLocalVmPortPath()->nexthop() &&
             route->FindLocalVmPortPath()->nexthop()->GetType()
                            == NextHop::COMPOSITE)) {
        AddCompositeRoute(route);
    } else if (uc_rt->GetActiveNextHop()->GetType() == NextHop::INTERFACE) {
        AddInterfaceRoute(route, route->FindLocalVmPortPath());
    }

    bool sync = false;
    if (old_peer_list != peer_list_) {
        sync = true;
    }

    std::set<const Peer *>::iterator it = old_peer_list.begin();
    while(it != old_peer_list.end()) {
        std::set<const Peer *>::iterator prev_it = it;
        it++;
        if (peer_list_.find(*prev_it) != peer_list_.end()) {
            old_peer_list.erase(prev_it);
        }
    }

    DeleteRoute(route, old_peer_list);

    if (sync) {
        InetUnicastAgentRouteTable *table = NULL;
        if (uc_rt && (uc_rt->GetTableType() == Agent::INET4_UNICAST)) {
            table = dest_vrf_->GetInet4UnicastRouteTable();
        } else if (uc_rt && (uc_rt->GetTableType() == Agent::INET6_UNICAST)) {
            table = dest_vrf_->GetInet6UnicastRouteTable();
        }
        table->ResyncRoute(agent_->fabric_rt_export_peer(),
                           dest_vrf_->GetName(), uc_rt->addr(), uc_rt->plen());
    }
}

void RouteLeakState::DeleteRoute(const AgentRoute *route,
                                 const std::set<const Peer *> &peer_list) {
    if (dest_vrf_ == NULL) {
        return;
    }

    std::set<const Peer *>::const_iterator it = peer_list.begin();
    for(; it != peer_list.end(); it++) {
        const InetUnicastRouteEntry *uc_rt =
            static_cast<const InetUnicastRouteEntry *>(route);
        InetUnicastAgentRouteTable *table = NULL;
        if (uc_rt && (uc_rt->GetTableType() == Agent::INET4_UNICAST)) {
            table = dest_vrf_->GetInet4UnicastRouteTable();
        } else if (uc_rt && (uc_rt->GetTableType() == Agent::INET4_UNICAST)) {
            table = dest_vrf_->GetInet6UnicastRouteTable();
        }
        table->Delete(*it,dest_vrf_->GetName(), uc_rt->addr(), uc_rt->plen());
    }
}

RouteLeakVrfState::RouteLeakVrfState(VrfEntry *source_vrf,
                                     VrfEntry *dest_vrf):
    source_vrf_(source_vrf), dest_vrf_(dest_vrf), deleted_(false) {

    AgentRouteTable *table = source_vrf->GetInet4UnicastRouteTable();
    route_listener_id_ = table->Register(boost::bind(&RouteLeakVrfState::Notify,
                                                      this, _1, _2));

    table = source_vrf->GetInet6UnicastRouteTable();
    route_listener_id6_ = table->Register(boost::bind(&RouteLeakVrfState::Notify,
                                                      this, _1, _2));

    //Walker would be used to address change of dest VRF table
    //Everytime dest vrf change all the route from old dest VRF
    //would be deleted and added to new dest VRF if any
    //If VRF is deleted upon walk done state would be deleted.

    // Intialize "table" again
    table = source_vrf->GetInet4UnicastRouteTable();
    walk_ref_ = table->AllocWalker(
                    boost::bind(&RouteLeakVrfState::WalkCallBack, this, _1, _2),
                    boost::bind(&RouteLeakVrfState::WalkDoneInternal, this, _2));
    table->WalkTable(walk_ref_);

    // Intialize "table" again
    table = source_vrf->GetInet6UnicastRouteTable();
    walk_ref_ip6_ = table->AllocWalker(
                    boost::bind(&RouteLeakVrfState::WalkCallBack, this, _1, _2),
                    boost::bind(&RouteLeakVrfState::WalkDoneInternal, this, _2));
    table->WalkTable(walk_ref_ip6_);
}

RouteLeakVrfState::~RouteLeakVrfState() {
    source_vrf_->GetInet6UnicastRouteTable()->ReleaseWalker(walk_ref_ip6_);
    source_vrf_->GetInet4UnicastRouteTable()->ReleaseWalker(walk_ref_);

    source_vrf_->GetInet6UnicastRouteTable()->Unregister(route_listener_id6_);
    source_vrf_->GetInet4UnicastRouteTable()->Unregister(route_listener_id_);
}

void RouteLeakVrfState::WalkDoneInternal(DBTableBase *part) {
    if (deleted_) {
        delete this;
    }
}

bool RouteLeakVrfState::WalkCallBack(DBTablePartBase *partition, DBEntryBase *entry) {
    Notify(partition, entry);
    return true;
}

void RouteLeakVrfState::AddDefaultRoute() {
    InetUnicastAgentRouteTable *table = source_vrf_->GetInet4UnicastRouteTable();

    VnListType vn_list;
    vn_list.insert(table->agent()->fabric_vn_name());

    table->AddGatewayRoute(table->agent()->local_peer(),
                           source_vrf_->GetName(), Ip4Address(0), 0,
                           table->agent()->vhost_default_gateway(), vn_list,
                           MplsTable::kInvalidLabel, SecurityGroupList(),
                           TagList(), CommunityList(), true);

    if (!table->agent()->router_id6().is_unspecified()) {
        table = source_vrf_->GetInet6UnicastRouteTable();
        table->AddGatewayRoute6(table->agent()->local_peer(),
                           source_vrf_->GetName(), Ip6Address(), 0,
                           table->agent()->vhost_default_gateway6(), vn_list,
                           MplsTable::kInvalidLabel, SecurityGroupList(),
                           TagList(), CommunityList(), true);
    }
}

void RouteLeakVrfState::DeleteDefaultRoute() {
    InetUnicastAgentRouteTable *table = source_vrf_->GetInet4UnicastRouteTable();
    table->Delete(table->agent()->local_peer(), source_vrf_->GetName(),
                  Ip4Address(0), 0);

    if (!table->agent()->router_id6().is_unspecified()) {
        table = source_vrf_->GetInet6UnicastRouteTable();
        table->Delete(table->agent()->local_peer(), source_vrf_->GetName(),
                  Ip6Address(), 0);
    }
}

void RouteLeakVrfState::Delete() {
    deleted_ = true;
    source_vrf_->GetInet6UnicastRouteTable()->WalkAgain(walk_ref_ip6_);
    source_vrf_->GetInet4UnicastRouteTable()->WalkAgain(walk_ref_);
    DeleteDefaultRoute();
}

bool RouteLeakVrfState::Notify(DBTablePartBase *partition, DBEntryBase *entry) {
    AgentRoute *route = static_cast<AgentRoute *>(entry);
    InetUnicastRouteEntry *uc_route = dynamic_cast<InetUnicastRouteEntry *>(entry);
    DBTableBase::ListenerId listener_id_;
    if (uc_route && (uc_route->GetTableType() == Agent::INET4_UNICAST)) {
        listener_id_ = route_listener_id_;
    } else if (uc_route && (uc_route->GetTableType() == Agent::INET6_UNICAST)) {
        listener_id_ = route_listener_id6_;
    } else {
        assert(0);
    }

    RouteLeakState *state =
        static_cast<RouteLeakState *>(entry->GetState(partition->parent(),
                                                      listener_id_));

    if (route->IsDeleted() || deleted_) {
        if (state) {
            //Delete the route
            entry->ClearState(partition->parent(), listener_id_);
            state->DeleteRoute(route, state->peer_list());
            delete state;
        }
        return true;
    }

    if (state == NULL && dest_vrf_) {
        if (uc_route && (uc_route->GetTableType() == Agent::INET4_UNICAST)) {
            state = new RouteLeakState(dest_vrf_->GetInet4UnicastRouteTable()->agent(),
                                   NULL);
        } else if (uc_route && (uc_route->GetTableType() == Agent::INET6_UNICAST)) {
            state = new RouteLeakState(dest_vrf_->GetInet6UnicastRouteTable()->agent(),
                                   NULL);
        }
        route->SetState(partition->parent(), listener_id_, state);
    }

    if (state == NULL) {
        return true;
    }

    if (state->dest_vrf() != dest_vrf_) {
        state->DeleteRoute(route, state->peer_list());
    }

    if (state->dest_vrf() != dest_vrf_) {
        //Add the route in new VRF
        state->set_dest_vrf(dest_vrf_.get());
    }

    if (state->dest_vrf()) {
        state->AddRoute(route);
    }
    return true;
}

void RouteLeakVrfState::SetDestVrf(VrfEntry *vrf) {
    if (dest_vrf_ != vrf) {
        dest_vrf_ = vrf;
        source_vrf_->GetInet4UnicastRouteTable()->WalkAgain(walk_ref_);
        source_vrf_->GetInet6UnicastRouteTable()->WalkAgain(walk_ref_ip6_);
    }

    if (vrf == NULL) {
        DeleteDefaultRoute();
    } else {
        AddDefaultRoute();
    }
}

RouteLeakManager::RouteLeakManager(Agent *agent): agent_(agent) {
    vrf_listener_id_ = agent_->vrf_table()->Register(
                           boost::bind(&RouteLeakManager::Notify, this, _1, _2));
}

RouteLeakManager::~RouteLeakManager() {
    agent_->vrf_table()->Unregister(vrf_listener_id_);
}

void RouteLeakManager::Notify(DBTablePartBase *partition, DBEntryBase *entry) {
    VrfEntry *vrf = static_cast<VrfEntry *>(entry);
    RouteLeakVrfState *state =
        static_cast<RouteLeakVrfState *>(entry->GetState(partition->parent(),
                                                         vrf_listener_id_));

    if (vrf->IsDeleted()) {
        if (state) {
            entry->ClearState(partition->parent(), vrf_listener_id_);
            state->Delete();
        }
        return;
    }


    if (state == NULL && vrf->forwarding_vrf()) {
        state = new RouteLeakVrfState(vrf, NULL);
    }

    if (state == NULL) {
        return;
    }

    vrf->SetState(partition->parent(), vrf_listener_id_, state);

    if (vrf->forwarding_vrf() != state->dest_vrf()) {
        state->SetDestVrf(vrf->forwarding_vrf());
    }
}

void RouteLeakManager::ReEvaluateRouteExports() {
    if (vrf_walk_ref_.get() == NULL) {
        vrf_walk_ref_ = agent_->vrf_table()->AllocWalker(
            boost::bind(&RouteLeakManager::VrfWalkNotify, this, _1, _2),
            boost::bind(&RouteLeakManager::VrfWalkDone, this, _2));
    }
    agent_->vrf_table()->WalkAgain(vrf_walk_ref_);
}

bool RouteLeakManager::VrfWalkNotify(DBTablePartBase *partition,
                                     DBEntryBase *e) {
    VrfEntry *vrf = static_cast<VrfEntry *>(e);
    RouteLeakVrfState *state =
        static_cast<RouteLeakVrfState *>(e->GetState(partition->parent(),
                                                     vrf_listener_id_));
    if (vrf->IsDeleted()) {
        return true;
    }
    /* Ignore VRFs on which routes are not leaked by RouteLeakManager */
    if (state == NULL) {
        return true;
    }
    if (state->deleted()) {
        return true;
    }

    StartRouteWalk(vrf, state);
    return true;
}

void RouteLeakManager::VrfWalkDone(DBTableBase *part) {
}

void RouteLeakManager::StartRouteWalk(VrfEntry *vrf, RouteLeakVrfState *state) {
    InetUnicastAgentRouteTable *table = vrf->GetInet4UnicastRouteTable();
    if (table) {
        DBTable::DBTableWalkRef rt_table_walk_ref = table->AllocWalker(
            boost::bind(&RouteLeakVrfState::Notify, state, _1, _2),
            boost::bind(&RouteLeakManager::RouteWalkDone, this, _2));
        table->WalkAgain(rt_table_walk_ref);
    }

    table = vrf->GetInet6UnicastRouteTable();
    if (table) {
        DBTable::DBTableWalkRef rt_table_walk_ref = table->AllocWalker(
            boost::bind(&RouteLeakVrfState::Notify, state, _1, _2),
            boost::bind(&RouteLeakManager::RouteWalkDone, this, _2));
        table->WalkAgain(rt_table_walk_ref);
    }
}

void RouteLeakManager::RouteWalkDone(DBTableBase *part) {
}
