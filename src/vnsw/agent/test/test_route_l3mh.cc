/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"
#include <boost/assign/list_of.hpp>
#include <base/logging.h>
#include <io/event_manager.h>
#include <tbb/task.h>
#include <base/task.h>

#include <cmn/agent_cmn.h>

#include <cfg/cfg_init.h>
#include "oper/operdb_init.h"
#include "controller/controller_init.h"
#include "pkt/pkt_init.h"
#include "services/services_init.h"
#include "vrouter/ksync/ksync_init.h"
#include "oper/interface_common.h"
#include "oper/nexthop.h"
#include "oper/tunnel_nh.h"
#include "route/route.h"
#include "oper/vrf.h"
#include "oper/mpls.h"
#include "oper/vm.h"
#include "oper/vn.h"
#include "filter/acl.h"
#include "oper/path_preference.h"
#include "test_cmn_util.h"
#include "kstate/test/test_kstate_util.h"
#include "vr_types.h"
#include "net/bgp_af.h"
#include <controller/controller_export.h>
#include "oper/vxlan_routing_manager.h"
#include "pkt/test/test_pkt_util.h"

#define ROUTE_L3MH_CONFIG_FILE \
        "controller/src/vnsw/agent/test/vnswa_l3mh_cfg.ini"

using namespace boost::assign;

class RouteTest : public ::testing::Test {
public:

protected:
    RouteTest() : vrf_name_("vrf1") {
        agent_ = Agent::GetInstance();

        fabric_gw_ip_1_ = agent_->vhost_default_gateway()[0];
        fabric_gw_ip_2_ = agent_->vhost_default_gateway()[1];
        eth_name_1_ = agent_->fabric_interface_name_list()[0];
        eth_name_2_ = agent_->fabric_interface_name_list()[1];
        server2_ip_ = Ip4Address::from_string("10.1.122.11");
        remote_vm_ip_ = Ip4Address::from_string("1.1.1.11");
    }

    virtual void SetUp() {
        boost::system::error_code ec;
        bgp_peer_ = CreateBgpPeer(Ip4Address::from_string("0.0.0.1", ec),
                                 "xmpp channel");
        client->WaitForIdle();

        //Create a VRF
        VrfAddReq(vrf_name_.c_str());
        client->WaitForIdle();

        client->Reset();
    }

    virtual void TearDown() {
        VrfDelReq(vrf_name_.c_str());
        client->WaitForIdle();

        TestRouteTable table1(2);
        WAIT_FOR(100, 1000, (table1.Size() == 0));
        EXPECT_EQ(table1.Size(), 0U);

        TestRouteTable table2(3);
        WAIT_FOR(100, 1000, (table2.Size() == 0));
        EXPECT_EQ(table2.Size(), 0U);

        TestRouteTable table3(4);
        WAIT_FOR(100, 1000, (table3.Size() == 0));
        EXPECT_EQ(table3.Size(), 0U);

        WAIT_FOR(100, 1000, (VrfFind(vrf_name_.c_str()) != true));
        WAIT_FOR(1000, 1000, agent_->vrf_table()->Size() == 2);
        DeleteBgpPeer(bgp_peer_);
    }

    void AddRemoteVmRoute(const Ip4Address &remote_vm_ip,
                          const Ip4Address &server_ip, uint32_t plen,
                          uint32_t label, TunnelType::TypeBmap bmap) {
        //Passing vn name as vrf name itself
        Inet4TunnelRouteAdd(bgp_peer_, vrf_name_, remote_vm_ip, plen, server_ip,
                            bmap, label, vrf_name_,
                            SecurityGroupList(), TagList(), PathPreference());
        client->WaitForIdle();
    }

    void DeleteRoute(const Peer *peer, const std::string &vrf_name,
                     const Ip4Address &addr, uint32_t plen) {
        AgentRoute *rt = RouteGet(vrf_name, addr, plen);
        uint32_t path_count = rt->GetPathList().size();
        agent_->fabric_inet4_unicast_table()->DeleteReq(peer, vrf_name, addr,
                                                        plen, NULL);
        client->WaitForIdle(5);
        WAIT_FOR(1000, 10000, ((RouteFind(vrf_name, addr, plen) != true) ||
                               (rt->GetPathList().size() == (path_count - 1))));
    }

    std::string vrf_name_;
    std::string eth_name_1_;
    std::string eth_name_2_;
    Ip4Address  fabric_gw_ip_1_;
    Ip4Address  fabric_gw_ip_2_;
    Ip4Address  server2_ip_;
    Ip4Address  remote_vm_ip_;
    Agent *agent_;
    BgpPeer *bgp_peer_;
};

TEST_F(RouteTest, RemoteVmRoute_5) {
    //Add remote VM route IP, pointing to 0.0.0.0
    AddRemoteVmRoute(remote_vm_ip_, server2_ip_, 32,
                     MplsTable::kStartLabel, TunnelType::AllType());
    EXPECT_TRUE(RouteFind(vrf_name_, remote_vm_ip_, 32));
    InetUnicastRouteEntry *addr_rt = RouteGet(vrf_name_, remote_vm_ip_, 32);
    const NextHop *addr_nh = addr_rt->GetActiveNextHop();
    EXPECT_TRUE(addr_nh->IsValid() == false);

    // Try to send a packet from VM, flow underlay_gw index should be -1
    struct PortInfo input[] = {
        {"vnet1", 1, "1.1.1.1", "00:00:00:01:01:01", 1, 1},
    };
    IpamInfo ipam_info_1[] = {
        {"1.1.1.0", 24, "1.1.1.254"},
    };
    Ip4Address local_vm_ip_ = Ip4Address::from_string("1.1.1.1");
    AddIPAM("vn1", ipam_info_1, 1);
    CreateVmportEnv(input, 1);
    client->WaitForIdle();
    EXPECT_TRUE(VmPortActive(input, 0));
    EXPECT_TRUE(RouteFind(vrf_name_, local_vm_ip_, 32));
    TxIpPacket(VmPortGetId(1), "1.1.1.1", remote_vm_ip_.to_string().c_str(), 1);
    client->WaitForIdle();
    FlowEntry *entry = FlowGet(VrfGet(vrf_name_.c_str())->vrf_id(),
                       "1.1.1.1", remote_vm_ip_.to_string().c_str(), 1, 0, 0, GetFlowKeyNH(1));
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->data().underlay_gw_index_ == 255);

    //Resolve ARP for gw1
    AddArp(fabric_gw_ip_1_.to_string().c_str(), "0a:0b:0c:0d:0e:0f",
           eth_name_1_.c_str());
    client->WaitForIdle();
    addr_nh = addr_rt->GetActiveNextHop();
    EXPECT_TRUE(addr_nh->IsValid() == true);

    //Resolve ARP for gw2
    AddArp(fabric_gw_ip_2_.to_string().c_str(), "0f:0e:0d:0c:0b:0a",
           eth_name_2_.c_str());
    client->WaitForIdle();
    addr_nh = addr_rt->GetActiveNextHop();
    EXPECT_TRUE(addr_nh->IsValid() == true);

    //Delete ARP for gw1
    DelArp(fabric_gw_ip_1_.to_string().c_str(), "0a:0b:0c:0d:0e:0f",
           eth_name_1_.c_str());
    client->WaitForIdle();
    addr_nh = addr_rt->GetActiveNextHop();
    EXPECT_TRUE(addr_nh->IsValid() == true);

    //Delete ARP for gw2
    DelArp(fabric_gw_ip_2_.to_string().c_str(), "0f:0e:0d:0c:0b:0a",
           eth_name_2_.c_str());
    client->WaitForIdle();
    addr_nh = addr_rt->GetActiveNextHop();
    EXPECT_TRUE(addr_nh->IsValid() == false);

    //Delete remote server route
    DeleteRoute(bgp_peer_, vrf_name_, remote_vm_ip_, 32);
    EXPECT_FALSE(RouteFind(vrf_name_, remote_vm_ip_, 32));

    DeleteVmportEnv(input, 1, true);
    client->WaitForIdle();
}

int main(int argc, char *argv[]) {
    ::testing::InitGoogleTest(&argc, argv);
    GETUSERARGS();
    client = TestInit(ROUTE_L3MH_CONFIG_FILE, ksync_init, true, false);
    int ret = RUN_ALL_TESTS();
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
