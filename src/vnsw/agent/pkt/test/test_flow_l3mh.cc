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
#include "test_flow_base.cc"

#define FLOW_L3MH_CONFIG_FILE \
        "controller/src/vnsw/agent/test/vnswa_l3mh_cfg.ini"
#define remote_router_ip_address  "10.1.122.1"

//Egress flow test  to verify flow stickiness (IP fabric to VMPort - Same VN)
//Flow creation using GRE packets
TEST_F(FlowTest, FlowStickiness_1) {
    EXPECT_EQ(0U, get_flow_proto()->FlowCount());
    //Create PHYSICAL interface to receive GRE packets on it.
    eth_itf = "vnet0";
    PhysicalInterfaceKey key(eth_itf);
    Interface *intf = static_cast<Interface *>
        (agent()->interface_table()->FindActiveEntry(&key));
    EXPECT_TRUE(intf != NULL);

    Ip4Address fabric_gw_ip_1_ = agent_->vhost_default_gateway()[0];
    Ip4Address fabric_gw_ip_2_ = agent_->vhost_default_gateway()[1];
    std::string eth_name_1_ = agent_->fabric_interface_name_list()[0];
    std::string eth_name_2_ = agent_->fabric_interface_name_list()[1];
    AddArp(fabric_gw_ip_1_.to_string().c_str(), "0a:0b:0c:0d:0e:0f",
           eth_name_1_.c_str());
    client->WaitForIdle();
    AddArp(fabric_gw_ip_2_.to_string().c_str(), "0f:0e:0d:0c:0b:0a",
           eth_name_2_.c_str());
    client->WaitForIdle();
    //Create remote VM route. This will be used to figure out destination VN for
    //flow
    CreateRemoteRoute("vrf5", remote_vm1_ip, remote_router_ip_address, 30, "vn5");
    client->WaitForIdle();

    CreateRemoteRoute("vrf5", remote_vm3_ip, remote_router_ip_address, 32, "vn5");
    client->WaitForIdle();

    TestFlow flow[] = {
        //Send an ICMP flow from remote VM to local VM
        {
            TestFlowPkt(Address::INET, remote_vm1_ip, vm1_ip, 1, 0, 0, "vrf5",
                    remote_router_ip_address, flow0->label()),
            {
                new VerifyVn("vn5", "vn5"),
                new VerifyVrf("vrf5", "vrf5")
            }
        },
        //Send a ICMP reply from local to remote VM
        {
            TestFlowPkt(Address::INET, vm1_ip, remote_vm1_ip, 1, 0, 0, "vrf5",
                    flow0->id()),
            {
                new VerifyVn("vn5", "vn5"),
                new VerifyVrf("vrf5", "vrf5")
            }
        },
        //Send a TCP flow from remote VM to local VM
        {
            TestFlowPkt(Address::INET, remote_vm3_ip, vm3_ip, IPPROTO_TCP, 1001, 1002,
                    "vrf5", remote_router_ip_address, flow2->label()),
            {
                new VerifyVn("vn5", "vn5"),
                new VerifyVrf("vrf5", "vrf5")
            }
        },
        //Send a TCP reply from local VM to remote VM
        {
            TestFlowPkt(Address::INET, vm3_ip, remote_vm3_ip, IPPROTO_TCP, 1002, 1001,
                    "vrf5", flow2->id()),
            {
                new VerifyVn("vn5", "vn5"),
                new VerifyVrf("vrf5", "vrf5")
            }
        }
    };

    CreateFlow(flow, 4);
    EXPECT_EQ(4U, get_flow_proto()->FlowCount());

    //Verify ingress and egress flow count
    uint32_t in_count, out_count;
    const FlowEntry *fe = flow[0].pkt_.FlowFetch();
    const VnEntry *vn = fe->data().vn_entry.get();
    // Non local flow as incoming interface is fabric interface
    EXPECT_FALSE(fe->is_flags_set(FlowEntry::LocalFlow));
    // Packet reveived on phyical interface 0 , underlay_gw_index is 0 for fw and rev flow
    EXPECT_TRUE(fe->data().underlay_gw_index_ == 0);
    EXPECT_TRUE(fe->reverse_flow_entry()->data().underlay_gw_index_ == 0);
    get_flow_proto()->VnFlowCounters(vn, &in_count, &out_count);
    EXPECT_EQ(2U, in_count);
    EXPECT_EQ(2U, out_count);

    //1. Remove remote VM routes
    DeleteRemoteRoute("vrf5", remote_vm1_ip);
    DeleteRemoteRoute("vrf5", remote_vm3_ip);
    client->WaitForIdle();
}

//Egress flow test to verify flow stickines (IP fabric to VMport - Different VNs)
//Flow creation using GRE packets
TEST_F(FlowTest, FlowStickiness_2) {
    /* Add remote VN route to vrf5 */
    CreateRemoteRoute("vrf5", remote_vm4_ip, remote_router_ip_address, 8, "vn3");

    TestFlow flow[] = {
        //Send an ICMP flow from remote VM in vn3 to local VM in vn5
        {
            TestFlowPkt(Address::INET, remote_vm4_ip, vm1_ip, 1, 0, 0, "vrf5",
                    remote_router_ip_address, flow0->label()),
            {
                new VerifyVn("vn3", "vn5"),
            }
        },
        //Send a ICMP reply from local VM in vn5 to remote VM in vn3
        {
            TestFlowPkt(Address::INET, vm1_ip, remote_vm4_ip, 1, 0, 0, "vrf5",
                    flow0->id()),
            {
                new VerifyVn("vn5", "vn3"),
            }
        },
        //Send a TCP flow from remote VM in vn3 to local VM in vn5
        {
            TestFlowPkt(Address::INET, remote_vm4_ip, vm1_ip, IPPROTO_TCP, 1006, 1007,
                    "vrf5", remote_router_ip_address, flow0->label()),
            {
                new VerifyVn("vn3", "vn5"),
            }
        },
        //Send a TCP reply from local VM in vn5 to remote VM in vn3
        {
            TestFlowPkt(Address::INET, vm1_ip, remote_vm4_ip, IPPROTO_TCP, 1007, 1006,
                    "vrf5", flow0->id()),
            {
                new VerifyVn("vn5", "vn3"),
            }
        }
    };

    CreateFlow(flow, 4);
    client->WaitForIdle();
    //Verify ingress and egress flow count of VN "vn5"
    uint32_t in_count, out_count;
    const FlowEntry *fe = flow[0].pkt_.FlowFetch();
    const VnEntry *vn = fe->data().vn_entry.get();
    get_flow_proto()->VnFlowCounters(vn, &in_count, &out_count);
    EXPECT_EQ(2U, in_count);
    EXPECT_EQ(2U, out_count);

    //Verify ingress and egress flow count of VN "vn3"
    fe = flow[1].pkt_.FlowFetch();
    vn = fe->data().vn_entry.get();
    get_flow_proto()->VnFlowCounters(vn, &in_count, &out_count);
    EXPECT_EQ(2U, in_count);
    EXPECT_EQ(2U, out_count);

    // Non local flow as incoming interface is fabric interface
    EXPECT_FALSE(fe->is_flags_set(FlowEntry::LocalFlow));
    // Packet reveived on phyical interface 1 , underlay_gw_index is 1 for fw and rev flows
    EXPECT_TRUE(fe->data().underlay_gw_index_ == 1);
    EXPECT_TRUE(fe->reverse_flow_entry()->data().underlay_gw_index_ == 1);

    //1. Remove remote VM routes
    DeleteRemoteRoute("vrf5", remote_vm4_ip);
    client->WaitForIdle();
}

//For local flow underlay gw index is -1
TEST_F(FlowTest, FlowStickiness_3) {
    TestFlow flow[] = {
        //Add a ICMP forward and reverse flow
        {  TestFlowPkt(Address::INET, vm1_ip, vm2_ip, 1, 0, 0, "vrf5",
                       flow0->id()),
        {
            new VerifyVn("vn5", "vn5"),
            new VerifyVrf("vrf5", "vrf5"),
            new VerifyDestVrf("vrf5", "vrf5")
        }
        },
        {  TestFlowPkt(Address::INET, vm2_ip, vm1_ip, 1, 0, 0, "vrf5",
                       flow1->id()),
        {
            new VerifyVn("vn5", "vn5"),
            new VerifyVrf("vrf5", "vrf5"),
            new VerifyDestVrf("vrf5", "vrf5")
        }
        },
        //Add a TCP forward and reverse flow
        {  TestFlowPkt(Address::INET, vm1_ip, vm2_ip, IPPROTO_TCP, 1000, 200,
                       "vrf5", flow0->id()),
        {
            new VerifyVn("vn5", "vn5"),
            new VerifyVrf("vrf5", "vrf5"),
            new VerifyDestVrf("vrf5", "vrf5")
        }
        },
        {  TestFlowPkt(Address::INET, vm2_ip, vm1_ip, IPPROTO_TCP, 200, 1000,
                       "vrf5", flow1->id()),
        {
            new VerifyVn("vn5", "vn5"),
            new VerifyVrf("vrf5", "vrf5"),
            new VerifyDestVrf("vrf5", "vrf5")
        }
        }
    };

    CreateFlow(flow, 4);
    EXPECT_EQ(4U, get_flow_proto()->FlowCount());

    //Verify the ingress and egress flow counts
    uint32_t in_count, out_count;
    const FlowEntry *fe = flow[0].pkt_.FlowFetch();
    const FlowEntry *fe1 = flow[2].pkt_.FlowFetch();

   //for local flow underlay gw index is set to -1
   EXPECT_TRUE(fe->is_flags_set(FlowEntry::LocalFlow));
   EXPECT_TRUE(fe->data().underlay_gw_index_ == 255);
   EXPECT_TRUE(fe->reverse_flow_entry()->data().underlay_gw_index_ == 255);
   EXPECT_TRUE(fe1->is_flags_set(FlowEntry::LocalFlow));
   EXPECT_TRUE(fe1->data().underlay_gw_index_ == 255);
   EXPECT_TRUE(fe1->reverse_flow_entry()->data().underlay_gw_index_ == 255);
}

int main(int argc, char *argv[]) {
    GETUSERARGS();

    client =
        TestInit(FLOW_L3MH_CONFIG_FILE, ksync_init, true, false);
    client->WaitForIdle();
    int ret = RUN_ALL_TESTS();
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
