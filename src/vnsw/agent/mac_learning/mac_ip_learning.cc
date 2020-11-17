/*
 * Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
 */
#include <init/agent_param.h>
#include <oper/vn.h>
#include <oper/sg.h>
#include <oper/vrf.h>
#include <oper/nexthop.h>
#include <oper/interface_common.h>
#include <oper/route_common.h>
#include "mac_learning_proto.h"
#include "mac_ip_learning_proto_handler.h"
#include "mac_learning_init.h"
#include "mac_ip_learning.h"
#include "mac_learning_mgmt.h"
#include "mac_learning_event.h"


MacIpLearningTable::MacIpLearningTable(Agent *agent, MacLearningProto *proto) :
    agent_(agent),
    work_queue_(this) {
    agent->health_check_table()->RegisterHealthCheckNotifyCallback(
            boost::bind(&MacIpLearningTable::MacIpEntryHcNotify, this, _1));
}

bool MacIpLearningTable::RequestHandler(MacLearningEntryRequestPtr ptr) {
    switch(ptr->event()) {
    case MacLearningEntryRequest::VROUTER_MSG:
        agent()->mac_learning_proto()->ProcessProto(ptr->pkt_info());
        break;

    case MacLearningEntryRequest::ADD_MAC:
        Add(ptr->mac_learning_entry());
        break;

    case MacLearningEntryRequest::RESYNC_MAC:
        Resync(ptr->mac_learning_entry());
        break;

    case MacLearningEntryRequest::DELETE_MAC:
        Delete(ptr->mac_learning_entry());
        break;
    case MacLearningEntryRequest::REMOTE_MAC_IP:
        DetectIpMove(ptr);
        break;

    case MacLearningEntryRequest::MAC_IP_UNREACHABLE:
        MacIpEntryUnreachable(ptr);
        break;

    default:
        assert(0);
    }
    return true;
}
void MacIpLearningTable::EnqueueMgmtReq(MacLearningEntryPtr ptr, bool add) {
    MacLearningMgmtRequest::Event e = MacLearningMgmtRequest::ADD_MAC_IP;
    if (add == false) {
        e = MacLearningMgmtRequest::DELETE_MAC_IP;
    }
    MacLearningMgmtRequestPtr req(new MacLearningMgmtRequest(e, ptr));
    agent()->mac_learning_module()->mac_learning_mgmt()->Enqueue(req);
}
void MacIpLearningTable::Add(MacLearningEntryPtr ptr) {
    MacIpLearningEntry *entry = dynamic_cast<MacIpLearningEntry *>(ptr.get());
    MacIpLearningKey key(entry->vrf_id(), entry->IpAddr());
    //check whether IP belongs to subnet of VN
    const VmInterface *vm_intf =
        dynamic_cast<const VmInterface *>(entry->intf());
    if (!vm_intf ||
            !vm_intf->vn()->GetIpam(entry->IpAddr())) {
        MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                    entry->IpAddr().to_string(), entry->Mac().ToString(),
                    entry->intf()->name(),
                    "ip address does not belong to same subnet, ignoring");
        return;
    }
    if (vm_intf->mac() == entry->Mac()) {
        MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                    entry->IpAddr().to_string(), entry->Mac().ToString(),
                    entry->intf()->name(),
                    "mac address is same as of interface , ignoring");
        return;
    }
    MacIpLearningEntryMap::iterator it = mac_ip_learning_entry_map_.find(key);
    if (it != mac_ip_learning_entry_map_.end()) {
        MacIpLearningEntry *existing_entry =
            dynamic_cast<MacIpLearningEntry *>(it->second.get());
        if ( existing_entry && existing_entry->Mac() == entry->Mac()) {
            // ignore duplicate add requests, it is possible that
            // duplicate requests may come till route processing is done.
            MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                    entry->IpAddr().to_string(), entry->Mac().ToString(),
                    entry->intf()->name(),
                    "duplicate add request, ingoring");
            return;
        }
        MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                    entry->IpAddr().to_string(), entry->Mac().ToString(),
                    entry->intf()->name(),
                    "local IP move detected, delete and add with new mac");
        //Entry already present, clear the entry
        if (it->second->deleted() == false) {
            it->second->Delete();
            EnqueueMgmtReq(it->second, false);
        }
        mac_ip_learning_entry_map_[key] = ptr;
    } else {
        // check whether mac limit reached for learning new mac-ip
        // on the interface
        if (vm_intf->IsMaxMacIpLearnt()) {
            MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                        entry->IpAddr().to_string(), entry->Mac().ToString(),
                        entry->intf()->name(),
                        "max mac ip learnt limit reached on interface");
            return;
        }

        mac_ip_learning_entry_map_.insert(MacIpLearningEntryPair(key, ptr));
    }
    ptr->Add();
    EnqueueMgmtReq(ptr, true);
}

void MacIpLearningTable::Delete(const MacLearningEntryPtr ptr) {
    if (ptr->deleted() == true) {
        return;
    }
    MacIpLearningEntry *entry = dynamic_cast<MacIpLearningEntry *>(ptr.get());
    if (entry == NULL) {
        return;
    }

    MacIpLearningKey key(ptr->vrf_id(), entry->IpAddr());
    if (mac_ip_learning_entry_map_.find(key) == mac_ip_learning_entry_map_.end()) {
        return;
    }
    MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                    entry->IpAddr().to_string(), entry->Mac().ToString(),
                    entry->intf()->name(), "Delete");

    ptr->Delete();
    mac_ip_learning_entry_map_.erase(key);
    EnqueueMgmtReq(ptr, false);
}

void MacIpLearningTable::Resync(MacLearningEntryPtr ptr) {
    MacIpLearningEntry *entry = dynamic_cast<MacIpLearningEntry *>(ptr.get());
    if (entry == NULL) {
        return;
    }
    MacIpLearningKey key(ptr->vrf_id(), entry->IpAddr());
    if (mac_ip_learning_entry_map_.find(key) == mac_ip_learning_entry_map_.end()) {
        return;
    }

    MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, entry->vrf()->GetName(),
                    entry->IpAddr().to_string(), entry->Mac().ToString(),
                    entry->intf()->name(), "Resync");
    ptr->Resync();
    EnqueueMgmtReq(ptr, true);
}

void MacIpLearningTable::DetectIpMove(MacLearningEntryRequestPtr ptr) {
    const EvpnRouteEntry *route = dynamic_cast<const EvpnRouteEntry *>(ptr->db_entry());
    MacIpLearningKey key(route->vrf_id(), route->ip_addr());
    MacIpLearningEntryMap::iterator it = mac_ip_learning_entry_map_.find(key);
    if (it == mac_ip_learning_entry_map_.end()) {
        return;
    }
    MacIpLearningEntry *mac_ip_entry = dynamic_cast<MacIpLearningEntry *>( it->second.get());
    if (mac_ip_entry->Mac() == route->mac()) {
        return;
    }
    MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, route->vrf()?route->vrf()->GetName():"NULL",
                    route->ip_addr().to_string(), mac_ip_entry->Mac().ToString(),
                    mac_ip_entry->intf()->name(),
                    "IP Move detected, deleting local entry");

    it->second->Delete();
    EnqueueMgmtReq(it->second, false);
    mac_ip_learning_entry_map_.erase(key);
}
void MacIpLearningTable::MacIpEntryUnreachable(uint32_t vrf_id, IpAddress &ip,
                                                            MacAddress &mac) {
    MacLearningEntryRequestPtr ptr(new MacLearningEntryRequest(
                                   MacLearningEntryRequest::MAC_IP_UNREACHABLE,
                                   vrf_id, ip, mac));
    Enqueue(ptr);
}
void MacIpLearningTable::MacIpEntryHcNotify(
            const HealthCheckInstanceService *instance_service) {
    const HealthCheckMacIpInstanceService *mac_ip_instance_service =
        dynamic_cast<const HealthCheckMacIpInstanceService *>(instance_service);
    if (mac_ip_instance_service) {
        IpAddress ip = mac_ip_instance_service->destination_ip();
        MacAddress mac = mac_ip_instance_service->destination_mac();
        uint32_t vrf_id =
            mac_ip_instance_service->interface()->vrf()->vrf_id();
        MacLearningEntryRequestPtr ptr(new MacLearningEntryRequest(
                                   MacLearningEntryRequest::MAC_IP_UNREACHABLE,
                                   vrf_id, ip, mac));
        Enqueue(ptr);
    }
}
void MacIpLearningTable::MacIpEntryUnreachable(MacLearningEntryRequestPtr ptr) {
    MacIpLearningKey key(ptr->vrf_id(), ptr->ip());
    MacIpLearningEntryMap::iterator it = mac_ip_learning_entry_map_.find(key);
    if (it == mac_ip_learning_entry_map_.end()) {
        return;
    }
    MacIpLearningEntry *mac_ip_entry = dynamic_cast<MacIpLearningEntry *>( it->second.get());
    if (mac_ip_entry->Mac() == ptr->mac()) {
        MAC_IP_LEARNING_TRACE(MacLearningTraceBuf, mac_ip_entry->vrf()->GetName(),
                    mac_ip_entry->IpAddr().to_string(), mac_ip_entry->Mac().ToString(),
                    mac_ip_entry->intf()->name(), "MACIP unreachable, trigger delete");
        it->second->Delete();
        mac_ip_learning_entry_map_.erase(key);
        EnqueueMgmtReq(it->second, false);
    }
}

void MacIpLearningTable::Enqueue(MacLearningEntryRequestPtr req) {
    work_queue_.Enqueue(req);
    return;
}
MacIpLearningEntry*
MacIpLearningTable::Find(const MacIpLearningKey &key) {
    MacIpLearningEntryMap::iterator it = mac_ip_learning_entry_map_.find(key);
    if (it == mac_ip_learning_entry_map_.end()) {
        return NULL;
    }

    MacIpLearningEntry *mac_ip_entry = dynamic_cast<MacIpLearningEntry *>( it->second.get());
    return mac_ip_entry;
}
MacAddress MacIpLearningTable::GetPairedMacAddress(uint32_t vrf_id, const IpAddress& ip) {
    MacIpLearningKey key(vrf_id, ip);
    MacIpLearningEntry *entry = Find(key);
    if (entry) {
        return entry->Mac();
    }
    return  MacAddress();

}

MacIpLearningEntry::MacIpLearningEntry(MacIpLearningTable *table,
                uint32_t vrf_id, const IpAddress &ip,
                const MacAddress &mac, InterfaceConstRef intf) :
    MacLearningEntry(vrf_id), mac_ip_learning_table_(table),
    key_(vrf_id, ip), ip_(ip), mac_(mac),
    intf_(intf), vn_(NULL), hc_service_(NULL), hc_instance_(NULL) {
        const VmInterface *vm_port = dynamic_cast<const VmInterface *>(intf_.get());
        assert(vm_port);
        vn_ = vm_port->vn();

}
bool MacIpLearningEntry::Add() {
    VmInterfaceLearntMacIpData *data = new VmInterfaceLearntMacIpData();
    data->is_add = true;
    data->mac_ip_list_.list_.insert(
            VmInterface::LearntMacIp(ip_, mac_));
    DBRequest req;
    req.oper = DBRequest::DB_ENTRY_ADD_CHANGE;
    req.key.reset(new VmInterfaceKey(AgentKey::RESYNC, intf_->GetUuid(), ""));
    req.data.reset(data);
    mac_ip_learning_table_->agent()->interface_table()->Enqueue(&req);
    UpdateHealthCheckService();
    return 0;
}

void MacIpLearningEntry::Delete() {
    if (hc_instance_) {
        hc_instance_->StopTask(hc_service_);
        hc_instance_ = NULL;
        hc_service_ = NULL;
    }
    VmInterfaceLearntMacIpData *data = new VmInterfaceLearntMacIpData();
    data->is_add = false;
    data->mac_ip_list_.list_.insert(
            VmInterface::LearntMacIp(ip_, mac_));
    DBRequest req;
    req.oper = DBRequest::DB_ENTRY_ADD_CHANGE;
    req.key.reset(new VmInterfaceKey(AgentKey::RESYNC, intf_->GetUuid(), ""));
    req.data.reset(data);
    mac_ip_learning_table_->agent()->interface_table()->Enqueue(&req);
}

void MacIpLearningEntry::Resync() {
    UpdateHealthCheckService();
}

void MacIpLearningEntry::EnqueueToTable(MacLearningEntryRequestPtr req) {
        mac_ip_learning_table_->Enqueue(req);
}

void MacIpLearningEntry::UpdateHealthCheckService() {
    HealthCheckService *hc_service =
        GetHealthCheckService(vn_.get());
    if (hc_service_ != hc_service) {
        if (hc_service_ == NULL) {
            AddHealthCheckService(hc_service);
        } else {
            hc_instance_->StopTask(hc_service_);
            hc_instance_ = NULL;
            hc_service_= NULL;
            if (hc_service) {
                AddHealthCheckService(hc_service);
            }
        }
    } else if (hc_service_) {
        hc_instance_->UpdateInstanceTask();
    }
}
void MacIpLearningEntry::AddHealthCheckService(HealthCheckService *service) {
    if (service) {
        hc_service_ = service;
        IpAddress gateway_ip = vn_->GetGatewayFromIpam(ip_);
        const VmInterface *vm_intf = static_cast< const VmInterface *>(intf_.get());
        //TODO: add validation check for null gateway ip
        hc_instance_ = service->StartHealthCheckService(
                   const_cast< VmInterface *>(vm_intf), NULL,
                   gateway_ip, ip_, mac_, false, false);
        hc_instance_->set_service(hc_service_);
    }
}

HealthCheckService* MacIpLearningEntry::GetHealthCheckService(const VnEntry *vn) {
    //1. check if hc is attached
    const boost::uuids::uuid hc_uuid = vn->health_check_uuid();
    if (hc_uuid == boost::uuids::nil_uuid()) {
        return NULL;
    }
    HealthCheckService *hc_service = Agent::GetInstance()->
        health_check_table()->Find(hc_uuid);
    //2. if attached , check whether target ip present in tragte ip list
    if (!hc_service) {
        return NULL;
    }
    if (hc_service->IsTargetIpPresent(IpAddr())) {
            return hc_service;
    }

    return NULL;
}
MacIpLearningRequestQueue::MacIpLearningRequestQueue(MacIpLearningTable *table):
    table_(table),
    queue_(table_->agent()->task_scheduler()->GetTaskId(kTaskMacLearning),
            0,
            boost::bind(&MacIpLearningRequestQueue::HandleEvent,this,_1)) {
}

bool MacIpLearningRequestQueue::HandleEvent(MacLearningEntryRequestPtr ptr) {
    return table_->RequestHandler(ptr);
}
