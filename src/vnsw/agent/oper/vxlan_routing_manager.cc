/*
 * Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
 */

#include <boost/uuid/uuid_io.hpp>
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

using namespace std;

VxlanRoutingState::VxlanRoutingState(VxlanRoutingManager *mgr,
                                     VrfEntry *vrf) {
   inet4_table_ = vrf->GetInet4UnicastRouteTable();
   inet6_table_ = vrf->GetInet6UnicastRouteTable();
   evpn_table_ = vrf->GetEvpnRouteTable();
   std::string nm4 = std::string("vxlan_lstnr.") + inet4_table_->name();
   std::string nm6 = std::string("vxlan_lstnr.") + inet6_table_->name();
   std::string nme = std::string("vxlan_lstnr.") + evpn_table_->name();

   inet4_id_ = inet4_table_->
       Register(boost::bind(&VxlanRoutingManager::RouteNotify,
       mgr, _1, _2), nm4);
   inet6_id_ = inet6_table_->
       Register(boost::bind(&VxlanRoutingManager::RouteNotify,
       mgr, _1, _2), nm6);
   evpn_id_ = evpn_table_->
       Register(boost::bind(&VxlanRoutingManager::RouteNotify,
       mgr, _1, _2), nme);
}

VxlanRoutingState::~VxlanRoutingState() {
   evpn_table_->Unregister(evpn_id_);
   inet4_table_->Unregister(inet4_id_);
   inet6_table_->Unregister(inet6_id_);
}

VxlanRoutingVnState::VxlanRoutingVnState(VxlanRoutingManager *mgr) :
    vmi_list_(), is_routing_vn_(false),
    logical_router_uuid_(boost::uuids::nil_uuid()), mgr_(mgr) {
}

VxlanRoutingVnState::~VxlanRoutingVnState() {
}

void VxlanRoutingVnState::AddVmi(const VnEntry *vn, const VmInterface *vmi) {
    if (vmi->logical_router_uuid() == boost::uuids::nil_uuid()) {
        LOG(ERROR, "Error in VxlanRoutingManager::AddVmi"
        << ", vmi->logical_router_uuid() ==  boost::uuids::nil_uuid()");
        assert(vmi->logical_router_uuid() != boost::uuids::nil_uuid());
    }
    VmiListIter it = vmi_list_.find(vmi);
    if (it != vmi_list_.end()) {
        return;
    }

    vmi_list_.insert(vmi);
    if ((logical_router_uuid_ != vmi->logical_router_uuid()) &&
        (*(vmi_list_.begin()) == vmi)) {
        mgr_->BridgeVnNotify(vn, this);
    }
}

void VxlanRoutingVnState::DeleteVmi(const VnEntry *vn, const VmInterface *vmi) {
    VmiListIter it = vmi_list_.find(vmi);
    if (it == vmi_list_.end()) {
        return;
    }
    vmi_list_.erase(vmi);
    mgr_->BridgeVnNotify(vn, this);
}

VxlanRoutingVmiState::VxlanRoutingVmiState() :
    vn_entry_(NULL), logical_router_uuid_(boost::uuids::nil_uuid()) {
}

VxlanRoutingVmiState::~VxlanRoutingVmiState() {
}

boost::uuids::uuid VxlanRoutingVnState::logical_router_uuid() const {
    if (vmi_list_.size() == 0)
        return boost::uuids::nil_uuid();

    return (*(vmi_list_.begin()))->logical_router_uuid();
}

VxlanRoutingRouteWalker::VxlanRoutingRouteWalker(const std::string &name,
    VxlanRoutingManager *mgr, Agent *agent) :
    AgentRouteWalker(name, agent), mgr_(mgr) {
}

VxlanRoutingRouteWalker::~VxlanRoutingRouteWalker() {
}

// Only take notification of bridge inet routes.
// Change in them will trigger change in rest.
bool VxlanRoutingRouteWalker::RouteWalkNotify(DBTablePartBase *partition,
    DBEntryBase *e) {
    // Now route leaking is triggered by changes in the Inet table of
    // a bridge VRF instance
    const InetUnicastRouteEntry *inet_rt =
        dynamic_cast<const InetUnicastRouteEntry*>(e);
    if (inet_rt) {
        const VrfEntry *vrf = inet_rt->vrf();
        if (vrf && vrf->vn() && !mgr_->IsRoutingVrf(vrf)) {
            mgr_->InetRouteNotify(partition, e);
        }
    }
    return true;
}

VxlanRoutingVrfMapper::VxlanRoutingVrfMapper(VxlanRoutingManager *mgr) :
    mgr_(mgr), lr_vrf_info_map_(), vn_lr_set_(),
    inet4_table_walker_(), inet6_table_walker_() {
}

VxlanRoutingVrfMapper::~VxlanRoutingVrfMapper() {
}

void VxlanRoutingVrfMapper::WalkBridgeInetTables(
    InetUnicastAgentRouteTable *inet4_table,
    InetUnicastAgentRouteTable *inet6_table) {
    // Inet 4
    {
        DBTable::DBTableWalkRef walk_ref;
        InetTableWalker::iterator it = inet4_table_walker_.find(inet4_table);
        if (it == inet4_table_walker_.end()) {
            walk_ref = inet4_table->
                AllocWalker(boost::bind(&VxlanRoutingManager::RouteNotify,
                                        mgr_, _1, _2),
                            boost::bind(&VxlanRoutingVrfMapper::BridgeInet4RouteWalkDone,
                                        this, _1, _2));
            inet4_table_walker_[inet4_table] = walk_ref;
        } else {
            walk_ref = it->second;
        }
        inet4_table->WalkAgain(walk_ref);
        //Every time walk is issued for bridge table revisit subnet routes
        mgr_->HandleSubnetRoute(inet4_table->vrf_entry());
    }
    // Inet 6
    {
        DBTable::DBTableWalkRef walk_ref;
        InetTableWalker::iterator it = inet6_table_walker_.find(inet6_table);
        if (it == inet6_table_walker_.end()) {
            walk_ref = inet6_table->
                AllocWalker(boost::bind(&VxlanRoutingManager::RouteNotify,
                                        mgr_, _1, _2),
                            boost::bind(&VxlanRoutingVrfMapper::BridgeInet6RouteWalkDone,
                                        this, _1, _2));
            inet6_table_walker_[inet6_table] = walk_ref;
        } else {
            walk_ref = it->second;
        }
        inet6_table->WalkAgain(walk_ref);
        //Every time walk is issued for bridge table revisit subnet routes
        mgr_->HandleSubnetRoute(inet6_table->vrf_entry());
    }
}

void VxlanRoutingVrfMapper::WalkRoutingVrf(const boost::uuids::uuid &lr_uuid,
                    const VnEntry *vn, bool update, bool withdraw) {
    if (lr_uuid == boost::uuids::nil_uuid())
        return;
    VxlanRoutingVrfMapper::RoutedVrfInfo &routing_vrf_info =
            lr_vrf_info_map_[lr_uuid];
    const VrfEntry *routing_vrf = routing_vrf_info.routing_vrf_;
    DBTable::DBTableWalkRef walk_ref;
    EvpnAgentRouteTable *evpn_table = NULL;
    if (withdraw) {
        const VrfEntry *bridge_vrf = vn->GetVrf();
        if (bridge_vrf && routing_vrf) {
            evpn_table =
            static_cast<EvpnAgentRouteTable *>(
                bridge_vrf->GetEvpnRouteTable());
        }
        if (!evpn_table) {
            return;
        }
        walk_ref = evpn_table->
        AllocWalker(boost::bind(&VxlanRoutingManager::WithdrawEvpnRouteFromRoutingVrf,
            mgr_, routing_vrf, _1, _2),
            boost::bind(&VxlanRoutingVrfMapper::RoutingVrfRouteWalkDone,
            this, _1, _2));
        evpn_table->WalkAgain(walk_ref);
    } else {
        if (routing_vrf) {
            evpn_table =
            static_cast<EvpnAgentRouteTable *>(
                routing_vrf->GetEvpnRouteTable());
        }
        if (!evpn_table) {
            return;
        }

        walk_ref = evpn_table->
        AllocWalker(boost::bind(&VxlanRoutingManager::LeakRoutesIntoBridgeTables,
            mgr_, _1, _2, lr_uuid, vn, update),
            boost::bind(&VxlanRoutingVrfMapper::RoutingVrfRouteWalkDone,
            this, _1, _2));
        evpn_table->WalkAgain(walk_ref);
    }
}

void VxlanRoutingVrfMapper::RoutingVrfRouteWalkDone(DBTable::DBTableWalkRef walk_ref,
                                          DBTableBase *partition) {
    if (walk_ref.get() != NULL)
        (static_cast<DBTable *>(partition))->ReleaseWalker(walk_ref);
}

void VxlanRoutingVrfMapper::BridgeInet4RouteWalkDone(DBTable::DBTableWalkRef walk_ref,
                                          DBTableBase *partition) {
    const InetUnicastAgentRouteTable *table = static_cast<const InetUnicastAgentRouteTable *>
        (walk_ref->table());
    InetTableWalker::iterator it = inet4_table_walker_.find(table);
    if(it == inet4_table_walker_.end()) {
        LOG(ERROR, "Error in VxlanRoutingManager::BridgeInet4RouteWalkDone"
        << ", it == inet4_table_walker_.end()");
        assert(it != inet4_table_walker_.end());
    }
    inet4_table_walker_.erase(it);
}

void VxlanRoutingVrfMapper::BridgeInet6RouteWalkDone(DBTable::DBTableWalkRef walk_ref,
                                          DBTableBase *partition) {
    const InetUnicastAgentRouteTable *table = static_cast<const InetUnicastAgentRouteTable *>
        (walk_ref->table());
    InetTableWalker::iterator it = inet6_table_walker_.find(table);
    if(it == inet6_table_walker_.end()){    
        LOG(ERROR, "Error in VxlanRoutingManager::BridgeInet6RouteWalkDone"
        << ", it == inet6_table_walker_.end()");
        assert(it != inet6_table_walker_.end());
    }

    inet6_table_walker_.erase(it);
}

void VxlanRoutingVrfMapper::WalkBridgeVrfs
(const VxlanRoutingVrfMapper::RoutedVrfInfo &routed_vrf_info)
{
    // Start walk on all l3 tables
    VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter it =
        routed_vrf_info.bridge_vn_list_.begin();
    while (it != routed_vrf_info.bridge_vn_list_.end()) {
        const VnEntry *vn = static_cast<const VnEntry *>(*it);
        const VrfEntry *vrf = vn->GetVrf();
        if (vrf) {
            InetUnicastAgentRouteTable *inet4_table =
                static_cast<InetUnicastAgentRouteTable *>
                (vrf->GetInet4UnicastRouteTable());
                InetUnicastAgentRouteTable *inet6_table =
                static_cast<InetUnicastAgentRouteTable *>
                (vrf->GetInet6UnicastRouteTable());
            if (!inet4_table || !inet6_table)
                continue;
            WalkBridgeInetTables(inet4_table, inet6_table);
        }
        it++;
    }
}

const VrfEntry *VxlanRoutingVrfMapper::GetRoutingVrfUsingVn
(const VnEntry *vn) {
    VnLrSetIter it = vn_lr_set_.find(vn);
    if (it != vn_lr_set_.end()) {
        return GetRoutingVrfUsingUuid(it->second);
    }
    return NULL;
}

const VrfEntry *VxlanRoutingVrfMapper::GetRoutingVrfUsingAgentRoute
(const AgentRoute *rt) {
    return GetRoutingVrfUsingUuid(GetLogicalRouterUuidUsingRoute(rt));
}

const VrfEntry *VxlanRoutingVrfMapper::GetRoutingVrfUsingUuid
(const boost::uuids::uuid &lr_uuid) {
    LrVrfInfoMapIter it = lr_vrf_info_map_.find(lr_uuid);
    if (it != lr_vrf_info_map_.end()) {
        return it->second.routing_vrf_;
    }
    return NULL;
}

const boost::uuids::uuid VxlanRoutingVrfMapper::GetLogicalRouterUuidUsingRoute
(const AgentRoute *rt) {
    using boost::uuids::nil_uuid;

    if (VxlanRoutingManager::IsRoutingVrf(rt->vrf())) {
        return rt->vrf()->vn()->logical_router_uuid();
    }

    const VnEntry* rt_vn = rt->vrf()->vn();
    if (!rt_vn) {
        return nil_uuid();
    }

    const VxlanRoutingVnState *vn_state =
        dynamic_cast<const VxlanRoutingVnState *>(rt_vn->
                           GetAgentDBEntryState(mgr_->vn_listener_id()));
    if ((vn_state == NULL) || (vn_state->vmi_list_.size() == 0)) {
        return nil_uuid();
    }

    return vn_state->logical_router_uuid_;
}

// Invoked everytime when a vrf is pulled out of use.
// Holds on object till all bridge and routing vrf are gone.
void VxlanRoutingVrfMapper::TryDeleteLogicalRouter(LrVrfInfoMapIter &it) {
    if ((it->second.routing_vrf_ == NULL) &&
        (it->second.bridge_vn_list_.size() == 0)) {
        lr_vrf_info_map_.erase(it);
    }
}

const Peer *VxlanRoutingManager::routing_vrf_interface_peer_ = NULL;
const Peer *VxlanRoutingManager::routing_vrf_vxlan_bgp_peer_ = NULL;

/**
 * VxlanRoutingManager
 */
VxlanRoutingManager::VxlanRoutingManager(Agent *agent) :
    agent_(agent), walker_(), vn_listener_id_(),
    vrf_listener_id_(), vmi_listener_id_(), vrf_mapper_(this) {
    //routing_vrf_interface_peer_ = agent_->evpn_routing_peer();
    routing_vrf_interface_peer_ = agent_->local_vm_export_peer();
    routing_vrf_vxlan_bgp_peer_ = agent_->vxlan_bgp_peer();
}

VxlanRoutingManager::~VxlanRoutingManager() {
}

void VxlanRoutingManager::Register() {
   // Walker to go through routes in bridge evpn tables.
   walker_.reset(new VxlanRoutingRouteWalker("VxlanRoutingManager", this,
                                             agent_));
   agent_->oper_db()->agent_route_walk_manager()->
       RegisterWalker(static_cast<AgentRouteWalker *>(walker_.get()));

   // Register all listener ids.
   vn_listener_id_ = agent_->vn_table()->
       Register(boost::bind(&VxlanRoutingManager::VnNotify,
                            this, _1, _2));
   vrf_listener_id_ = agent_->vrf_table()->Register(
       boost::bind(&VxlanRoutingManager::VrfNotify, this, _1, _2));
   vmi_listener_id_ = agent_->interface_table()->Register(
       boost::bind(&VxlanRoutingManager::VmiNotify, this, _1, _2));
}

void VxlanRoutingManager::Shutdown() {
   agent_->vn_table()->Unregister(vn_listener_id_);
   agent_->vrf_table()->Unregister(vrf_listener_id_);
   agent_->interface_table()->Unregister(vmi_listener_id_);
   agent_->oper_db()->agent_route_walk_manager()->
       ReleaseWalker(walker_.get());
   walker_.reset(NULL);
}

/**
 * VNNotify
 * Handles routing vrf i.e. VRF meant for doing evpn routing.
 * Addition or deletion of same add/withdraws route imported from bridge vrf in
 * routing vrf.
 * Walk is issued for the routes of bridge vrf's evpn table.
 *
 * For bridge VRF, only delete of VN is handled here. Add has no operation as
 * add of VN does not give any info on LR/Routing VRF to use.
 * When delete is seen withdraw from the list of bridge list.
 */
void VxlanRoutingManager::VnNotify(DBTablePartBase *partition, DBEntryBase *e) {
    VnEntry *vn = dynamic_cast<VnEntry *>(e);
    VxlanRoutingVnState *vn_state = dynamic_cast<VxlanRoutingVnState *>
        (vn->GetAgentDBEntryState(vn_listener_id_));

    if (vn->IsDeleted() && vn_state != NULL) {
        if (vn_state->is_routing_vn_) {
            RoutingVnNotify(vn, vn_state);
        } else {
            BridgeVnNotify(vn, vn_state);
        }

        //Delete State
        vn->ClearState(partition->parent(), vn_listener_id_);
        delete vn_state;
        return;
    }

    if (!vn_state) {
        vn_state = new VxlanRoutingVnState(this);
        vn->SetState(partition->parent(), vn_listener_id_, vn_state);
    }

    if (vn->vxlan_routing_vn()) {
        vn_state->is_routing_vn_ = vn->vxlan_routing_vn();
    }

    vn_state->vrf_ref_ = vn->GetVrf();
    if (vn_state->is_routing_vn_) {
        vn_state->logical_router_uuid_ = vn->logical_router_uuid();
        RoutingVnNotify(vn, vn_state);
    } else {
        BridgeVnNotify(vn, vn_state);
    }

    return;
}

void UpdateLogicalRouterUuid(const VnEntry *vn,
                             VxlanRoutingVnState *vn_state) {
    using boost::uuids::nil_uuid;

    if (vn_state->vmi_list_.size() == 0) {
        vn_state->logical_router_uuid_ = nil_uuid();
    }

    VxlanRoutingVnState::VmiListIter it = vn_state->vmi_list_.begin();
    while (it != vn_state->vmi_list_.end()) {
        vn_state->logical_router_uuid_ = (*it)->logical_router_uuid();
        if ((*it)->logical_router_uuid() != nil_uuid()) {
            return;
        }
        //Delete VMI with no lr uuid, vmi update will handle rest.
        vn_state->vmi_list_.erase(it);
        if (vn_state->vmi_list_.size() == 0) {
            vn_state->logical_router_uuid_ = nil_uuid();
            return;
        }
        it = vn_state->vmi_list_.begin();
    }
    return;
}

void VxlanRoutingManager::BridgeVnNotify(const VnEntry *vn,
                                         VxlanRoutingVnState *vn_state) {
    using boost::uuids::nil_uuid;

    if (vn->logical_router_uuid() != nil_uuid()) {
        return;
    }

    VxlanRoutingVrfMapper::VnLrSetIter it = vrf_mapper_.vn_lr_set_.find(vn);
    VxlanRoutingVrfMapper::LrVrfInfoMapIter routing_info_it =
        vrf_mapper_.lr_vrf_info_map_.end();
    bool withdraw = false;
    bool update = true;

    // Update lr uuid in case some vmi is deleted or added.
    UpdateLogicalRouterUuid(vn, vn_state);
    if (vn->IsDeleted() || (vn->GetVrf() == NULL)) {
        withdraw = true;
        update = false;
    }

    if (it != vrf_mapper_.vn_lr_set_.end() &&
        (it->second != vn_state->logical_router_uuid_) &&
        (vn_state->logical_router_uuid_ != nil_uuid())) {
        withdraw = true;
    }

    if (vn_state->logical_router_uuid_ == nil_uuid()) {
        withdraw = true;
        update = false;
    }

    if (it != vrf_mapper_.vn_lr_set_.end()) {
        routing_info_it = vrf_mapper_.lr_vrf_info_map_.find(it->second);
    }

    // Handles deletion case
    if (withdraw) {
        if (routing_info_it != vrf_mapper_.lr_vrf_info_map_.end()) {
            VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter br_it =
                routing_info_it->second.bridge_vn_list_.find(vn);
            std::string vrf_name = "";
            if (routing_info_it->second.bridge_vrf_names_list_.count(vn) == 1) {
                vrf_name = routing_info_it->second.bridge_vrf_names_list_.at(vn);
                DeleteSubnetRoute(vn, vrf_name);
            }
            if (br_it != routing_info_it->second.bridge_vn_list_.end()) {
                vrf_mapper_.WalkRoutingVrf(it->second, vn, false, true);
                routing_info_it->second.bridge_vn_list_.erase(br_it);
                routing_info_it->second.bridge_vrf_names_list_.erase(vn);
            }
            // Trigger delete of logical router
            vrf_mapper_.TryDeleteLogicalRouter(routing_info_it);
        }
        vrf_mapper_.vn_lr_set_.erase(vn);
    }

    if (update) {
        vrf_mapper_.vn_lr_set_[vn] = vn_state->logical_router_uuid_;
        if (vrf_mapper_.vn_lr_set_[vn] == nil_uuid()) {
            return;
        }

        VxlanRoutingVrfMapper::RoutedVrfInfo &lr_vrf_info =
            vrf_mapper_.lr_vrf_info_map_[vn_state->logical_router_uuid_];
        lr_vrf_info.bridge_vn_list_.insert(vn);
        if (vn->GetVrf())
            lr_vrf_info.bridge_vrf_names_list_[vn] = vn->GetVrf()->GetName();
        vrf_mapper_.WalkRoutingVrf(vrf_mapper_.vn_lr_set_[vn], vn, true, false);
    }

    // Without vrf walks cant be scheduled
    if (!vn_state->vrf_ref_.get()) {
        return;
    }

    // Walk Evpn table if withdraw or update was done
    if (update || withdraw) {
        InetUnicastAgentRouteTable *inet4_table =
            static_cast<InetUnicastAgentRouteTable *>(vn_state->vrf_ref_.get()->
                                               GetInet4UnicastRouteTable());
        InetUnicastAgentRouteTable *inet6_table =
            static_cast<InetUnicastAgentRouteTable *>(vn_state->vrf_ref_.get()->
                                               GetInet6UnicastRouteTable());
        if (inet4_table && inet6_table) {
            vrf_mapper_.WalkBridgeInetTables(inet4_table, inet6_table);
        }
    }
    return;
}

void VxlanRoutingManager::RoutingVrfDeleteAllRoutes(VrfEntry* rt_vrf) {
    if (rt_vrf == NULL) {
        return;
    }
    // Loop over all EVPN routes and delete them

    EvpnAgentRouteTable *evpn_table = dynamic_cast<EvpnAgentRouteTable *>
        (rt_vrf->GetEvpnRouteTable());
    if (evpn_table == NULL) {
        return;
    }
    EvpnRouteEntry *c_entry = dynamic_cast<EvpnRouteEntry *>
        (evpn_table->GetTablePartition(0)->GetFirst());

    const std::string vrf_name = rt_vrf->GetName();
    const uint32_t ethernet_tag = 0;
    const MacAddress mac_addr;
    while (c_entry) {
        const IpAddress prefix_ip = c_entry->ip_addr();
        const uint32_t plen = c_entry->GetVmIpPlen();

        // Compute next entry in advance
        if (c_entry && c_entry->get_table_partition())
            c_entry = dynamic_cast<EvpnRouteEntry *>
                (c_entry->get_table_partition()->GetNext(c_entry));
        else
            break;

        // Delete routes originated from bridge networks
        EvpnAgentRouteTable::DeleteReq(routing_vrf_interface_peer_,
            vrf_name,
            mac_addr,
            prefix_ip,
            plen,
            ethernet_tag, // ethernet_tag = 0 for Type5
            NULL);

        InetUnicastAgentRouteTable::DeleteReq(routing_vrf_interface_peer_,
            vrf_name, prefix_ip, plen, NULL);

        // Delete routes originated from BPG peers (EVPN Type5 table)
        EvpnAgentRouteTable::DeleteReq(routing_vrf_vxlan_bgp_peer_,
            vrf_name,
            mac_addr,
            prefix_ip,
            plen,
            ethernet_tag, // ethernet_tag = 0 for Type5
            NULL);

        InetUnicastAgentRouteTable::DeleteReq(routing_vrf_vxlan_bgp_peer_,
            vrf_name, prefix_ip, plen, NULL);
    }
}

void VxlanRoutingManager::RoutingVnNotify(const VnEntry *vn,
                                          VxlanRoutingVnState *vn_state) {

    bool withdraw = false;
    bool update = false;
    VxlanRoutingVrfMapper::VnLrSetIter it = vrf_mapper_.vn_lr_set_.find(vn);

    if (vn->IsDeleted() ||
        (vn->GetVrf() == NULL) ||
        (vn_state->is_routing_vn_ == false)) {
        update = false;
        withdraw = true;
    } else {
        update = true;
        if (it != vrf_mapper_.vn_lr_set_.end()) {
            // LR uuid changed, so withdraw from old and add new.
            if (it->second != vn_state->logical_router_uuid_) {
                withdraw = true;
            }
        }
    }

    if (withdraw && (it != vrf_mapper_.vn_lr_set_.end())) {
        VxlanRoutingVrfMapper::LrVrfInfoMapIter routing_info_it =
            vrf_mapper_.lr_vrf_info_map_.find(it->second);
        // Delete only if parent VN is same as notified VN coz it may so happen
        // that some other VN has taken the ownership  of this LR and
        // notification of same came before this VN.
        if (routing_info_it != vrf_mapper_.lr_vrf_info_map_.end()) {
            if (routing_info_it->second.routing_vn_ == vn) {
                RoutingVrfDeleteAllRoutes(vn->GetVrf());
                // Routing VN/VRF
                // Reset parent vn and routing vrf
                routing_info_it->second.routing_vn_ = NULL;
                routing_info_it->second.routing_vrf_ = NULL;
            }
            // Trigger delete of logical router
            vrf_mapper_.TryDeleteLogicalRouter(routing_info_it);
        }
        vrf_mapper_.vn_lr_set_.erase(it);
    }

    if (update) {
        if (vn_state->logical_router_uuid_ == boost::uuids::nil_uuid()) {
            return;
        }

        if (it == vrf_mapper_.vn_lr_set_.end()) {
            vrf_mapper_.vn_lr_set_[vn] = vn_state->logical_router_uuid_;
        }

        VxlanRoutingVrfMapper::RoutedVrfInfo &routed_vrf_info =
            vrf_mapper_.lr_vrf_info_map_[vn_state->logical_router_uuid_];
        // Take the ownership of LR
        routed_vrf_info.routing_vn_ = vn;
        if (routed_vrf_info.routing_vrf_ != vn->GetVrf()) {
            routed_vrf_info.routing_vrf_ = vn->GetVrf();
            vrf_mapper_.WalkBridgeVrfs(routed_vrf_info);
        }
    }
}

/**
 * Updates (sets or deletes) VxlanRoutingState for the given
 * modified VrfEntry
 */
void VxlanRoutingManager::VrfNotify(DBTablePartBase *partition,
                                    DBEntryBase *e) {
    VrfEntry *vrf = static_cast<VrfEntry *>(e);
    if (vrf->GetName().compare(agent_->fabric_vrf_name()) == 0)
        return;
    if (vrf->GetName().compare(agent_->fabric_policy_vrf_name()) == 0)
        return;

    VxlanRoutingState *state = dynamic_cast<VxlanRoutingState *>(vrf->
                             GetState(partition->parent(), vrf_listener_id_));
    if (vrf->IsDeleted()) {
        if (state) {
            vrf->ClearState(partition->parent(), vrf_listener_id_);
            delete state;
        }
    } else {
        // Vrf was added/changed.
        if (!state) {
            state = new VxlanRoutingState(this, vrf);
            vrf->SetState(partition->parent(), vrf_listener_id_, state);
        }
        if (vrf->vn() && vrf->vn()->vxlan_routing_vn()) {
            vrf->set_routing_vrf(true);
        }
    }
}

void VxlanRoutingManager::VmiNotify(DBTablePartBase *partition,
                                    DBEntryBase *e) {
    VmInterface *vmi = dynamic_cast<VmInterface *>(e);
    if (!vmi) {
        return;
    }

    VnEntry *vn = vmi->GetNonConstVn();
    VxlanRoutingVnState *vn_state = NULL;
    VxlanRoutingVmiState *vmi_state = dynamic_cast<VxlanRoutingVmiState *>(vmi->
                             GetAgentDBEntryState(vmi_listener_id_));
    if (vmi->IsDeleted() || (vn == NULL) ||
        (vmi->logical_router_uuid() == boost::uuids::nil_uuid())) {
        if (!vmi_state) {
            return;
        }
        vn = vmi_state->vn_entry_.get();
        vn_state = dynamic_cast<VxlanRoutingVnState *>
            (vn->GetAgentDBEntryState(vn_listener_id_));
        if (vn_state)
            vn_state->DeleteVmi(vn, vmi);
        vmi->ClearState(partition->parent(), vmi_listener_id_);
        delete vmi_state;
        return;
    }

    if ((vmi->device_type() != VmInterface::VMI_ON_LR) ||
        (vmi->vmi_type() != VmInterface::ROUTER)) {
        return;
    }

    if (vmi->logical_router_uuid() == boost::uuids::nil_uuid()) {
        return;
    }

    // Without VN no point of update
    if (!vn) {
        return;
    }

    if (!vmi_state) {
        vmi_state = new VxlanRoutingVmiState();
        vmi->SetState(partition->parent(), vmi_listener_id_, vmi_state);
        vmi_state->vn_entry_ = vn;
    }
    // Update logical_router_uuid
    vmi_state->logical_router_uuid_ = vmi->logical_router_uuid();

    // Its necessary to add state on VN so as to push VMI. VN notify can come
    // after VMI notify.
    VnNotify(vn->get_table_partition(), vn);
    // Now get VN state and add/delete VMI there
    vn_state = dynamic_cast<VxlanRoutingVnState *>
        (vn->GetAgentDBEntryState(vn_listener_id_));
    if (vn_state) {
        vn_state->AddVmi(vn, vmi);
    }
}

void VxlanRoutingManager::HandleSubnetRoute(const VrfEntry *vrf, bool bridge_vrf) {
    //
    // New version
    //
    if (vrf->vn() && vrf->vn()->vxlan_routing_vn() == false) {
        const VrfEntry *routing_vrf =
            vrf_mapper_.GetRoutingVrfUsingVn(vrf->vn());
        if (!routing_vrf || vrf->IsDeleted()) {
             DeleteSubnetRoute(vrf);
             vrf->vn()->set_lr_vrf(NULL);
        } else {
            UpdateSubnetRoute(vrf, routing_vrf);
            vrf->vn()->set_lr_vrf(routing_vrf);
        }
    }
}

void VxlanRoutingManager::DeleteIpamRoutes(const VnEntry *vn,
    const std::string& vrf_name,
    const IpAddress& ipam_prefix,
    const uint32_t plen) {
    if (vn == NULL || vrf_name == std::string(""))
        return;

    VxlanRoutingVrfMapper::VnLrSetIter lr_it = vrf_mapper_.vn_lr_set_.find(vn);

    if (lr_it == vrf_mapper_.vn_lr_set_.end() ||
        lr_it->second == boost::uuids::nil_uuid())
        return;

    VxlanRoutingVrfMapper::RoutedVrfInfo &lr_vrf_info =
        vrf_mapper_.lr_vrf_info_map_[lr_it->second];

    if (lr_vrf_info.bridge_vn_list_.size() == 0)
        return;

    VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter it =
        lr_vrf_info.bridge_vn_list_.begin();
    while (it != lr_vrf_info.bridge_vn_list_.end()) {
        if (vn == *it) {
            it++;
            continue;
        }

        (*it)->GetVrf()->GetInetUnicastRouteTable(ipam_prefix)->
            Delete(agent_->evpn_routing_peer(), (*it)->GetVrf()->GetName(),
                ipam_prefix, plen, NULL);
        it++;
    }
}

void VxlanRoutingManager::DeleteSubnetRoute(const VnEntry *vn, const std::string& vrf_name) {
    if (vn == NULL || vrf_name == std::string(""))
        return;
    std::vector<VnIpam> bridge_vn_ipam = vn->GetVnIpam();

    if (bridge_vn_ipam.size() == 0)
        return;

    VxlanRoutingVrfMapper::VnLrSetIter lr_it = vrf_mapper_.vn_lr_set_.find(vn);

    if (lr_it == vrf_mapper_.vn_lr_set_.end() ||
        lr_it->second == boost::uuids::nil_uuid())
        return;

    VxlanRoutingVrfMapper::RoutedVrfInfo &lr_vrf_info =
        vrf_mapper_.lr_vrf_info_map_[lr_it->second];

    if (lr_vrf_info.bridge_vn_list_.size() == 0)
        return;

    VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter it =
        lr_vrf_info.bridge_vn_list_.begin();
    while (it != lr_vrf_info.bridge_vn_list_.end()) {
        if (vn == *it) {
            it++;
            continue;
        }

        for (std::vector<VnIpam>::iterator ipam_itr = bridge_vn_ipam.begin();
            ipam_itr < bridge_vn_ipam.end(); ipam_itr++) {
            (*it)->GetVrf()->GetInetUnicastRouteTable(ipam_itr->ip_prefix)->
                Delete(agent_->evpn_routing_peer(), (*it)->GetVrf()->GetName(),
                    ipam_itr->GetSubnetAddress(), ipam_itr->plen, NULL);
        }
        std::vector<VnIpam> vn_ipam = (*it)->GetVnIpam();

        if (vn_ipam.size() == 0) {
            it++;
            continue;
        }
        for (std::vector<VnIpam>::iterator vn_ipam_itr = vn_ipam.begin();
            vn_ipam_itr < vn_ipam.end(); vn_ipam_itr++) {
            InetUnicastAgentRouteTable::DeleteReq(agent_->evpn_routing_peer(),
                vrf_name, vn_ipam_itr->GetSubnetAddress(),
                vn_ipam_itr->plen, NULL);
        }
        it++;
    }
}

//void VxlanRoutingManager::DeleteSubnetRoute(const VrfEntry *vrf, VnIpam *ipam) {
void VxlanRoutingManager::DeleteSubnetRoute(const VrfEntry *vrf) {
    if (vrf == NULL)
        return;
    DeleteSubnetRoute(vrf->vn(), vrf->GetName());
}

void VxlanRoutingManager::UpdateSubnetRoute(const VrfEntry *bridge_vrf,
                                             const VrfEntry *routing_vrf) {
    if (!bridge_vrf->vn())
        return;

    std::vector<VnIpam> bridge_vn_ipam = bridge_vrf->vn()->GetVnIpam();

    if (bridge_vn_ipam.size() == 0)
        return;

    VxlanRoutingVrfMapper::VnLrSetIter lr_it =
        vrf_mapper_.vn_lr_set_.find(bridge_vrf->vn());

    if (lr_it == vrf_mapper_.vn_lr_set_.end() ||
        lr_it->second == boost::uuids::nil_uuid())
        return;

    VxlanRoutingVrfMapper::RoutedVrfInfo &lr_vrf_info =
        vrf_mapper_.lr_vrf_info_map_[lr_it->second];

    if (lr_vrf_info.bridge_vn_list_.size() == 0)
        return;

    VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter it =
        lr_vrf_info.bridge_vn_list_.begin();
    while (it != lr_vrf_info.bridge_vn_list_.end()) {
        if (bridge_vrf->vn() == *it) {
            it++;
            continue;
        }

        for (std::vector<VnIpam>::iterator ipam_itr = bridge_vn_ipam.begin();
            ipam_itr < bridge_vn_ipam.end(); ipam_itr++) {
            DBRequest nh_req(DBRequest::DB_ENTRY_ADD_CHANGE);
            nh_req.key.reset(new VrfNHKey(routing_vrf->GetName(), false, false));
            nh_req.data.reset(new VrfNHData(false, false, false));
            (*it)->GetVrf()->GetInetUnicastRouteTable(ipam_itr->ip_prefix)->
            AddEvpnRoutingRoute(ipam_itr->ip_prefix, ipam_itr->plen, routing_vrf,
                        agent_->evpn_routing_peer(),
                        SecurityGroupList(),
                        CommunityList(),
                        PathPreference(),
                        EcmpLoadBalance(),
                        TagList(),
                        nh_req,
                        routing_vrf->vxlan_id(),
                        VnListType());
        }

        std::vector<VnIpam> vn_ipam = (*it)->GetVnIpam();
        for (std::vector<VnIpam>::iterator vn_ipam_itr = vn_ipam.begin();
            vn_ipam_itr != vn_ipam.end(); vn_ipam_itr++) {

            DBRequest nh_req(DBRequest::DB_ENTRY_ADD_CHANGE);
            nh_req.key.reset(new VrfNHKey(routing_vrf->GetName(), false, false));
            nh_req.data.reset(new VrfNHData(false, false, false));
            bridge_vrf->GetInetUnicastRouteTable(vn_ipam_itr->ip_prefix)->
            AddEvpnRoutingRoute(vn_ipam_itr->ip_prefix, vn_ipam_itr->plen, routing_vrf,
                        agent_->evpn_routing_peer(),
                        SecurityGroupList(),
                        CommunityList(),
                        PathPreference(),
                        EcmpLoadBalance(),
                        TagList(),
                        nh_req,
                        routing_vrf->vxlan_id(),
                        VnListType());
        }
        it++;
    }
}

/**
 * sandesh request
 */
void VxlanRoutingManager::FillSandeshInfo(VxlanRoutingResp *resp) {
    VxlanRoutingVrfMapper::LrVrfInfoMapIter it1 =
       vrf_mapper_.lr_vrf_info_map_.begin();
    std::vector<VxlanRoutingMap> vr_map;
    while (it1 != vrf_mapper_.lr_vrf_info_map_.end()) {
        VxlanRoutingMap vxlan_routing_map;
        vxlan_routing_map.set_logical_router_uuid(UuidToString(it1->first));
        vxlan_routing_map.set_routing_vrf(it1->second.routing_vrf_->
                                            GetName());
        vxlan_routing_map.set_parent_routing_vn(it1->second.routing_vn_->
                                            GetName());
        VxlanRoutingVrfMapper::RoutedVrfInfo::BridgeVnListIter it2 =
            it1->second.bridge_vn_list_.begin();
        while (it2 != it1->second.bridge_vn_list_.end()) {
            VxlanRoutingBridgeVrf bridge_vrf;
            if ((*it2)->GetVrf()) {
                bridge_vrf.set_bridge_vrf((*it2)->GetVrf()->GetName());
            }
            bridge_vrf.set_bridge_vn((*it2)->GetName());
            vxlan_routing_map.bridge_vrfs.push_back(bridge_vrf);
            it2++;
        }
        vr_map.push_back(vxlan_routing_map);
        it1++;
    }
    resp->set_vr_map(vr_map);
}

void VxlanRoutingReq::HandleRequest() const {
    VxlanRoutingResp *resp = new VxlanRoutingResp();
    Agent *agent = Agent::GetInstance();
    VxlanRoutingManager *vxlan_routing_mgr =
        agent->oper_db()->vxlan_routing_manager();
    if (vxlan_routing_mgr) {
        resp->set_context(context());
        vxlan_routing_mgr->FillSandeshInfo(resp);
    }
    resp->set_more(false);
    resp->Response();
    return;
}
