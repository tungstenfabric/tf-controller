/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#include <algorithm>
#include <base/os.h>
#include <base/address_util.h>
#include "test/test_cmn_util.h"
#include "test_flow_util.h"
#include "ksync/ksync_sock_user.h"
#include "oper/tunnel_nh.h"
#include "pkt/flow_table.h"

#define vm1_ip "11.1.1.1"
#define vm2_ip "22.1.1.1"
struct PortInfo input[] = {
        {"vmi0", 6, vm1_ip, "00:00:00:01:01:01", 5, 1},
        {"vmi1", 7, vm2_ip, "00:00:00:01:01:02", 5, 2},
};
IpamInfo ipam_info[] = {
    {"11.1.1.0", 24, "11.1.1.10"},
    {"22.1.1.0", 24, "22.1.1.10"},
};
VmInterface *vmi0;
VmInterface *vmi1;

class FlowAuditTest : public ::testing::Test {
public:
    FlowAuditTest() : agent_(Agent::GetInstance()) {
        flow_proto_ = agent_->pkt()->get_flow_proto();
        flow_stats_collector_ = agent_->flow_stats_manager()->
            default_flow_stats_collector_obj();
    }

    virtual void SetUp() {
        EXPECT_EQ(0U, get_flow_proto()->FlowCount());
        client->Reset();

        CreateVmportEnv(input, 2, 0);
        client->WaitForIdle();
        AddIPAM("vn5", ipam_info, 2);
        client->WaitForIdle();

        vmi0 = VmInterfaceGet(input[0].intf_id);
        vmi1 = VmInterfaceGet(input[1].intf_id);
        assert(vmi0);
        assert(vmi1);
        FlowStatsTimerStartStop(agent_, true);
        KFlowPurgeHold();
    }

    virtual void TearDown() {
        FlushFlowTable();
        client->Reset();

        DeleteVmportEnv(input, 2, true, 0);
        client->WaitForIdle();
        DelIPAM("vn5");
        client->WaitForIdle();
        FlowStatsTimerStartStop(agent_, false);
        KFlowPurgeHold();
    }

    bool FlowTableWait(size_t count) {
        int i = 1000;
        while (i > 0) {
            i--;
            if (get_flow_proto()->FlowCount() == count) {
                break;
            }
            client->WaitForIdle();
            usleep(1);
        }
        return (get_flow_proto()->FlowCount() == count);
    }

    void FlushFlowTable() {
        client->EnqueueFlowFlush();
        client->WaitForIdle();
        EXPECT_EQ(0U, get_flow_proto()->FlowCount());
    }

    void RunFlowAudit() {
        KSyncFlowMemory *flow_memory = agent_->ksync()->ksync_flow_memory();
        flow_memory->AuditProcess();
        // audit timeout set to 10 in case of test code.
        // Sleep for audit duration
        usleep(flow_memory->audit_timeout() * 2);
        flow_memory->AuditProcess();
    }

    void RunHoldFlowAudit() {
        KSyncFlowMemory *flow_memory = agent_->ksync()->ksync_flow_memory();
        flow_memory->AuditProcess();
        flow_memory->AuditProcess();
    }


    bool KFlowHoldAdd(uint32_t hash_id, int vrf, const char *sip,
                      const char *dip, int proto, int sport, int dport,
                      int nh_id, bool hold = true) {
        KSyncSockTypeMap *sock = static_cast<KSyncSockTypeMap *>(KSyncSock::Get(0));
        KSyncFlowMemory *flow_memory = agent_->ksync()->ksync_flow_memory();
        if (hash_id >= flow_memory->table_entries_count()) {
            return false;
        }

        vr_flow_entry *vr_flow = KSyncSockTypeMap::GetFlowEntry(hash_id);

        vr_flow_req req;
        req.set_fr_index(hash_id);
        IpAddress saddr = IpAddress::from_string(sip);
        IpAddress daddr = IpAddress::from_string(dip);

        uint64_t supper;
        uint64_t slower;
        uint64_t dupper;
        uint64_t dlower;

        IpToU64(saddr, daddr, &supper, &slower, &dupper, &dlower);
        req.set_fr_flow_sip_l(slower);
        req.set_fr_flow_sip_u(supper);
        req.set_fr_flow_dip_l(dlower);
        req.set_fr_flow_dip_u(dupper);

        req.set_fr_flow_proto(proto);
        req.set_fr_family(AF_INET);
        req.set_fr_flow_sport(htons(sport));
        req.set_fr_flow_dport(htons(dport));
        req.set_fr_flow_vrf(vrf);
        req.set_fr_flow_nh_id(nh_id);

        if (hold) {
            vr_flow->fe_action = VR_FLOW_ACTION_HOLD;
        } else {
            vr_flow->fe_action = VR_FLOW_ACTION_FORWARD;
        }
        vr_flow_req flow_info(req);
        sock->flow_map[hash_id] = flow_info;
        KSyncSockTypeMap::SetFlowEntry(&req, true);

        return true;
    }

    void KFlowPurgeHold() {
        KSyncFlowMemory *flow_memory = agent_->ksync()->ksync_flow_memory();
        for (size_t count = 0;
             count < flow_memory->table_entries_count();
             count++) {
            vr_flow_entry *vr_flow = KSyncSockTypeMap::GetFlowEntry(count);
            vr_flow->fe_action = VR_FLOW_ACTION_DROP;
            vr_flow_req req;
            req.set_fr_index(0);
            KSyncSockTypeMap::SetFlowEntry(&req, false);
        }

        return;
    }

    FlowProto *get_flow_proto() const { return flow_proto_; }
    Agent *agent() {return agent_;}

public:
    Agent *agent_;
    FlowProto *flow_proto_;
    FlowStatsCollectorObject* flow_stats_collector_;
};
// Validate flows audit
TEST_F(FlowAuditTest, FlowAudit_1) {
    // Create two hold-flows
    EXPECT_TRUE(KFlowHoldAdd(1, 1, "1.1.1.1", "2.2.2.2", 1, 0, 0, 0));
    EXPECT_TRUE(KFlowHoldAdd(2, 1, "2.2.2.2", "3.3.3.3", 1, 0, 0, 0));
    RunFlowAudit();
    EXPECT_TRUE(FlowTableWait(2));

    FlowEntry *fe = FlowGet(1, "1.1.1.1", "2.2.2.2", 1, 0, 0, 0);
    EXPECT_TRUE(fe != NULL && fe->is_flags_set(FlowEntry::ShortFlow) == true &&
                fe->short_flow_reason() == FlowEntry::SHORT_AUDIT_ENTRY);

    // Wait till flow-stats-collector sees the flows
    WAIT_FOR(1000, 1000, (flow_stats_collector_->Size() == 2));

    // Enqueue aging and validate flows are deleted
    client->EnqueueFlowAge();
    client->WaitForIdle();
    WAIT_FOR(1000, 1000, (get_flow_proto()->FlowCount() == 0U));
}

// Validate flow do not get deleted in following case,
// - Flow-audit runs and enqueues request to delete
// - Add flow before audit message is run
// - Flow-audit message should be ignored
TEST_F(FlowAuditTest, FlowAudit_2) {

    // Create the flow first
    string vrf_name = agent_->vrf_table()->FindVrfFromId(1)->GetName();
    TestFlow flow[] = {
        {
            TestFlowPkt(Address::INET, "1.1.1.1", "2.2.2.2", 1, 0, 0, vrf_name,
                        vmi0->id(), 1),
            {
            }
        }
    };
    CreateFlow(flow, 1);
    EXPECT_TRUE(FlowTableWait(2));

    uint32_t nh_id = vmi0->flow_key_nh()->id();
    // Validate that flow-drop-reason is not AUDIT
    FlowEntry *fe = FlowGet(1, "1.1.1.1", "2.2.2.2", 1, 0, 0, nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() != FlowEntry::SHORT_AUDIT_ENTRY);

    // Wait till flow-stats-collector sees the flows
    WAIT_FOR(1000, 1000, (flow_stats_collector_->Size() == 2));

    // Enqueue Audit message
    EXPECT_TRUE(KFlowHoldAdd(nh_id, 1, "1.1.1.1", "2.2.2.2", 1, 0, 0, 0));
    RunFlowAudit();
    client->WaitForIdle();

    // Validate that flow-drop-reason is not AUDIT
    fe = FlowGet(1, "1.1.1.1", "2.2.2.2", 1, 0, 0, nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() != FlowEntry::SHORT_AUDIT_ENTRY);
}

// Validate hold flows
TEST_F(FlowAuditTest, FlowAudit_3) {
    uint32_t hold_flow_count;
    // Create two hold-flows
    EXPECT_TRUE(KFlowHoldAdd(1, 1, "1.1.1.1", "2.2.2.2", 1, 0, 0, 0));
    EXPECT_TRUE(KFlowHoldAdd(2, 1, "2.2.2.2", "3.3.3.3", 1, 0, 0, 0));
    RunHoldFlowAudit();
    hold_flow_count  = agent_->stats()->hold_flow_count();
    EXPECT_TRUE(hold_flow_count>=0);

    EXPECT_TRUE(KFlowHoldAdd(1, 1, "1.1.1.1", "2.2.2.2", 1, 0, 0, 0));
    EXPECT_TRUE(KFlowHoldAdd(2, 1, "2.2.2.2", "3.3.3.3", 1, 0, 0, 0));
    EXPECT_TRUE(KFlowHoldAdd(3, 1, "3.3.3.3", "4.4.4.4", 1, 0, 0, 0));
    EXPECT_TRUE(KFlowHoldAdd(4, 1, "4.4.4.4", "5.5.5.5", 1, 0, 0, 0));
    RunHoldFlowAudit();
    hold_flow_count  = agent_->stats()->hold_flow_count();
    EXPECT_TRUE(hold_flow_count>0);
}
// create reverse flow hold entry first and
// then send traffic , reverse flow creation request
// fails due to eexist, verify that flows are deleted
// during flow audit process.
TEST_F(FlowAuditTest, FlowAudit_4) {
    KSyncSockTypeMap *sock = static_cast<KSyncSockTypeMap *>(KSyncSock::Get(0));
    sock->set_is_incremental_index(true);

    // Create the flow first
    string vrf_name = agent_->vrf_table()->FindVrfFromId(2)->GetName();
    uint32_t rev_flow_nh_id = vmi1->flow_key_nh()->id();
    uint32_t fwd_flow_nh_id = vmi0->flow_key_nh()->id();
    // Enqueue Audit message
    EXPECT_TRUE(KFlowHoldAdd(2, 2, "22.1.1.1", "11.1.1.1", 1, 0, 0,
                                rev_flow_nh_id));
    TestFlow flow[] = {
        {
            TestFlowPkt(Address::INET, "11.1.1.1", "22.1.1.1", 1, 0, 0,
                    vrf_name, vmi0->id(), 1),
            {
            }
        }
    };
    CreateFlow(flow, 1);
    EXPECT_TRUE(FlowTableWait(2));

    // Validate that flow is not short flow
    FlowEntry *fe = FlowGet(1, "11.1.1.1", "22.1.1.1", 1, 0, 0, fwd_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == 0);
    fe = FlowGet(2,  "22.1.1.1", "11.1.1.1",  1, 0, 0, rev_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == 0 &&
                fe->ksync_entry()->ksync_response_error()
                == EEXIST);

    // Wait till flow-stats-collector sees the flows
    WAIT_FOR(1000, 1000, (flow_stats_collector_->Size() == 2));

    RunFlowAudit();
    client->WaitForIdle();

    // Validate that flow-drop-reason is not AUDIT
    fe = FlowGet(1, "11.1.1.1", "22.1.1.1", 1, 0, 0, fwd_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == FlowEntry::SHORT_AUDIT_ENTRY);
    fe = FlowGet(2,  "22.1.1.1", "11.1.1.1",  1, 0, 0, rev_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == FlowEntry::SHORT_AUDIT_ENTRY);
}

/* If eexist error is received for flow entry, and entry is not in hold state
 * in vrouter, also interface in flow entry has aap configured make flow entry
 * short flow with reason SHORT_FAILED_VROUTER_INSTALL
*/
TEST_F(FlowAuditTest, FlowAudit_Aap_Eexist_Error) {
    KSyncSockTypeMap *sock = static_cast<KSyncSockTypeMap *>(KSyncSock::Get(0));
    sock->set_is_incremental_index(true);

    // Configure allowed address pair on vmi1
    Ip4Address ip = Ip4Address::from_string("10.10.10.10");
    MacAddress mac("0a:0b:0c:0d:0e:0f");
    AddAap("vmi1", 7, ip, mac.ToString());
    EXPECT_TRUE(vmi1->allowed_address_pair_list().list_.size() == 1);

    // Create the flow first
    string vrf_name = agent_->vrf_table()->FindVrfFromId(2)->GetName();
    uint32_t rev_flow_nh_id = vmi1->flow_key_nh()->id();
    uint32_t fwd_flow_nh_id = vmi0->flow_key_nh()->id();
    // Add rev flow entry in hold state in vrouter
    EXPECT_TRUE(KFlowHoldAdd(2, 2, "22.1.1.1", "11.1.1.1", 1, 0, 0,
                                rev_flow_nh_id));
    TestFlow flow[] = {
        {
            TestFlowPkt(Address::INET, "11.1.1.1", "22.1.1.1", 1, 0, 0,
                    vrf_name, vmi0->id(), 1),
            {
            }
        }
    };
    CreateFlow(flow, 1);
    EXPECT_TRUE(FlowTableWait(2));

    // Validate that flow is not short flow as rev flow entry is in hold state
    FlowEntry *fe = FlowGet(1, "11.1.1.1", "22.1.1.1", 1, 0, 0, fwd_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == 0);
    //Validate that flow is not short flow as rev flow entry is in hold state,
    // eexist error for rev flow is expected
    fe = FlowGet(2,  "22.1.1.1", "11.1.1.1",  1, 0, 0, rev_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == 0 &&
                fe->ksync_entry()->ksync_response_error()
                == EEXIST);

    // delete flow entry from agent and vrouter
    KFlowPurgeHold();
    client->WaitForIdle();
    FlushFlowTable();

    // Add rev flow in vrouter with action forward
    EXPECT_TRUE(KFlowHoldAdd(2, 2, "22.1.1.1", "11.1.1.1", 1, 0, 0,
                                rev_flow_nh_id, false));
    // send traffic to add fwd and rev flow
    CreateFlow(flow, 1);
    EXPECT_TRUE(FlowTableWait(2));
    // Validate that flow-drop-reason is SHORT_FAILED_VROUTER_INSTALL
    fe = FlowGet(1, "11.1.1.1", "22.1.1.1", 1, 0, 0, fwd_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == FlowEntry::SHORT_FAILED_VROUTER_INSTALL);
    fe = FlowGet(2,  "22.1.1.1", "11.1.1.1",  1, 0, 0, rev_flow_nh_id);
    EXPECT_TRUE(fe != NULL &&
                fe->short_flow_reason() == FlowEntry::SHORT_FAILED_VROUTER_INSTALL
                && fe->ksync_entry()->ksync_response_error() == EEXIST);
}

// Validate flow do not get deleted in following case,
int main(int argc, char *argv[]) {
    GETUSERARGS();
    client = TestInit(init_file, ksync_init, true, true, true, 100*1000);
    int ret = RUN_ALL_TESTS();
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
