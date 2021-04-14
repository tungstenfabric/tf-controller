/*
 * Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"
#include <sys/socket.h>

#include <net/if.h>

#ifdef __linux__
#include <linux/netlink.h>
#include <linux/if_tun.h>
#include <linux/if_packet.h>
#endif

#ifdef __FreeBSD__
#include <sys/sockio.h>
#include <ifaddrs.h>
#endif

#include "testing/gunit.h"

#include <base/logging.h>
#include <io/event_manager.h>
#include <tbb/task.h>
#include <base/task.h>

#include <cmn/agent_cmn.h>

#include "cfg/cfg_init.h"
#include "oper/operdb_init.h"
#include "controller/controller_init.h"
#include "pkt/pkt_init.h"
#include "services/services_init.h"
#include "vrouter/ksync/ksync_init.h"
#include "oper/interface_common.h"
#include "oper/nexthop.h"
#include "route/route.h"
#include "oper/vrf.h"
#include "oper/mpls.h"
#include "oper/vm.h"
#include "oper/vn.h"
#include "filter/acl.h"
#include "test_cmn_util.h"
#include "vr_types.h"
#include <controller/controller_export.h>
#include <ksync/ksync_sock_user.h>
#include <boost/assign/list_of.hpp>

using namespace boost::assign;

#define NULL_VRF ""
#define ZERO_IP "0.0.0.0"

#define DEFAULT_VN "default-domain:default-project:ip-fabric"

#define VNSW_VHOST_L3MH_CONFIG_FILE \
    "controller/src/vnsw/agent/test/vnswa_l3mh_cfg.ini"

IpamInfo ipam_info[] = {
    {"10.1.1.0", 24, "10.1.1.10"},
};

class VHostMultiHomeTest : public ::testing::Test {
public:
    virtual void SetUp() {
        agent = Agent::GetInstance();
        vnswif_ = agent->ksync()->vnsw_interface_listner();
        client->WaitForIdle();

        AddVn(DEFAULT_VN, 1);
        AddIPAM(DEFAULT_VN, ipam_info, 1);

        std::stringstream str;
        str << "<display-name>" << "vhost0" << "</display-name>";
        AddNode("virtual-machine-interface", "vhost0", 10, str.str().c_str());
        AddLink("virtual-machine-interface", "vhost0",
                "virtual-network", DEFAULT_VN);

        peer_ = CreateBgpPeer(Ip4Address(1), "BGP Peer 1");
        fabric_gw_ip_1_ = agent->vhost_default_gateway()[0];
        fabric_gw_ip_2_ = agent->vhost_default_gateway()[1];
        eth_name_1_ = agent->fabric_interface_name_list()[0];
        eth_name_2_ = agent->fabric_interface_name_list()[1];
        client->WaitForIdle();
    }

    virtual void TearDown() {
        DelIPAM(DEFAULT_VN);
        DelVn(DEFAULT_VN);
        //DelNode("virtual-machine-interface", "vhost0");
        DelLink("virtual-machine-interface", "vhost0",
                "virtual-network", DEFAULT_VN);
        client->WaitForIdle();

        DeleteBgpPeer(peer_);
        client->WaitForIdle();
        WAIT_FOR(100, 1000, (agent->vrf_table()->Size() == 2U));
        WAIT_FOR(100, 1000, (agent->vm_table()->Size() == 0U));
        WAIT_FOR(100, 1000, (agent->vn_table()->Size() == 0U));
    }

    void SetSeen (string &if_name, bool oper, uint32_t id) {
        vnswif_->SetSeen(if_name, oper, id);
    }

    std::string eth_name_1_;
    std::string eth_name_2_;
    Ip4Address  fabric_gw_ip_1_;
    Ip4Address  fabric_gw_ip_2_;
    Agent *agent;
    BgpPeer *peer_;
    VnswInterfaceListener *vnswif_;
};

TEST_F(VHostMultiHomeTest, CrossConnect) {
    const VmInterface *vm_intf =
        static_cast<const VmInterface *>(VhostGet("vhost0"));
    EXPECT_TRUE(vm_intf->parent_list()[0]->name() == "vnet0");
    EXPECT_TRUE(vm_intf->parent_list()[1]->name() == "vnet1");
    EXPECT_TRUE(vm_intf->vm_mac().ToString() == agent->vrrp_mac().ToString());
    EXPECT_TRUE(vm_intf->vmi_type() == VmInterface::VHOST);
    EXPECT_TRUE(vm_intf->bridging() == false);
    EXPECT_TRUE(vm_intf->proxy_arp_mode() == VmInterface::PROXY_ARP_NONE);
}


TEST_F(VHostMultiHomeTest, ResolveRoute) {
    Ip4Address ip1 = Ip4Address::from_string("10.1.1.0");
    Ip4Address ip2 = Ip4Address::from_string("20.1.1.0");

    EXPECT_FALSE(RouteFind(agent->fabric_policy_vrf_name(), ip1, 24));
    EXPECT_FALSE(RouteFind(agent->fabric_policy_vrf_name(), ip2, 24));

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip1, 24));
    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip2, 24));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip1, 24);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RESOLVE);
    rt = RouteGet(agent->fabric_vrf_name(), ip2, 24);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RESOLVE);
}

TEST_F(VHostMultiHomeTest, VerifyReceiveRoute) {
    Ip4Address ip = agent->loopback_ip();

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip, 32));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip, 32);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RECEIVE);
}

TEST_F(VHostMultiHomeTest, DefaultRoute) {
    Ip4Address ip = Ip4Address::from_string("0.0.0.0");

    EXPECT_TRUE(RouteFind(agent->fabric_policy_vrf_name(), ip, 0));

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip, 0));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip, 0);
    const NextHop *nh = rt->GetActiveNextHop();
    EXPECT_TRUE(nh->GetType() == NextHop::COMPOSITE);
    const CompositeNH *comp_nh = static_cast<const CompositeNH *>(nh);
    EXPECT_TRUE(comp_nh->ComponentNHCount() == 2);
    const NextHop *nh1 = comp_nh->GetNH(0);
    const NextHop *nh2 = comp_nh->GetNH(1);
    EXPECT_TRUE(nh1->GetType() == NextHop::ARP);
    EXPECT_TRUE(nh2->GetType() == NextHop::ARP);

    //Verify no gw for default route as nh is  composite nh in policy vrf (1)
    EXPECT_TRUE(RouteFind(agent->fabric_policy_vrf_name(), ip, 0));
    rt = RouteGet(agent->fabric_policy_vrf_name(), ip, 0);
    EXPECT_TRUE(rt->GetActivePath()->gw_ip() == ip);
}

TEST_F(VHostMultiHomeTest, VerifyL2ReceiveRoute) {
    MacAddress mac1(0x00, 0x00, 0x00, 0x00, 0x00, 0x01);
    MacAddress mac2(0x00, 0x00, 0x00, 0x00, 0x00, 0x02);

    BridgeRouteEntry *rt = L2RouteGet(agent->fabric_vrf_name(), mac1);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::L2_RECEIVE);

    rt = L2RouteGet(agent->fabric_vrf_name(), mac2);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::L2_RECEIVE);
}

TEST_F(VHostMultiHomeTest, VerifyGwArpNexthop) {
    Ip4Address ip1 = Ip4Address::from_string("10.1.1.254");
    Ip4Address ip2 = Ip4Address::from_string("20.1.1.254");

    EXPECT_FALSE(RouteFind(agent->fabric_policy_vrf_name(), ip1, 32));
    EXPECT_FALSE(RouteFind(agent->fabric_policy_vrf_name(), ip2, 32));

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip1, 32));
    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip2, 32));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip1, 32);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::ARP);
    rt = RouteGet(agent->fabric_vrf_name(), ip2, 32);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::ARP);
}

TEST_F(VHostMultiHomeTest, VerifyPhyIntfL3ReceiveRoute) {
    Ip4Address ip1 = Ip4Address::from_string("10.1.1.1");
    Ip4Address ip2 = Ip4Address::from_string("20.1.1.1");
    
    EXPECT_FALSE(RouteFind(agent->fabric_policy_vrf_name(), ip1, 32));
    EXPECT_FALSE(RouteFind(agent->fabric_policy_vrf_name(), ip2, 32));

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip1, 32));
    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip2, 32));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip1, 32);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RECEIVE);
    rt = RouteGet(agent->fabric_vrf_name(), ip2, 32);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RECEIVE);
}

TEST_F(VHostMultiHomeTest, DefaultRouteArpTriggers) {
    Ip4Address ip = Ip4Address::from_string("0.0.0.0");

    EXPECT_TRUE(RouteFind(agent->fabric_policy_vrf_name(), ip, 0));

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip, 0));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip, 0);
    const NextHop *nh = rt->GetActiveNextHop();
    EXPECT_TRUE(nh->GetType() == NextHop::COMPOSITE);
    const CompositeNH *comp_nh = static_cast<const CompositeNH *>(nh);
    EXPECT_TRUE(comp_nh->ComponentNHCount() == 2);
    const NextHop *nh1 = comp_nh->GetNH(0);
    const NextHop *nh2 = comp_nh->GetNH(1);
    EXPECT_TRUE(nh1->GetType() == NextHop::ARP);
    EXPECT_TRUE(nh2->GetType() == NextHop::ARP);

    /* Verify both ArpNH are invalid */
    EXPECT_TRUE(nh1->IsValid() == false);
    EXPECT_TRUE(nh2->IsValid() == false);

    /* AddArp for first gw, verify first ArpNH becomes valid */
    AddArp(fabric_gw_ip_1_.to_string().c_str(), "0a:0b:0c:0d:0e:0f",
            eth_name_1_.c_str());
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == true);
    EXPECT_TRUE(nh2->IsValid() == false);

    /* AddArp for second gw, verify second ArpNH becomes valid */
    AddArp(fabric_gw_ip_2_.to_string().c_str(), "0f:0e:0d:0c:0b:0a",
            eth_name_2_.c_str());
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == true);
    EXPECT_TRUE(nh2->IsValid() == true);

    /* DelArp for first gw, verify first ArpNH becoms invalid */
    DelArp(fabric_gw_ip_1_.to_string().c_str(), "0a:0b:0c:0d:0e:0f",
            eth_name_1_.c_str());
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == false);
    EXPECT_TRUE(nh2->IsValid() == true);

    /* DelArp for second gw, verify second ArpNH becoms invalid */
    DelArp(fabric_gw_ip_2_.to_string().c_str(), "0f:0e:0d:0c:0b:0a",
            eth_name_2_.c_str());
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == false);
    EXPECT_TRUE(nh2->IsValid() == false);
}

TEST_F(VHostMultiHomeTest, DefaultRouteInterfaceTriggers) {
    Ip4Address ip = Ip4Address::from_string("0.0.0.0");

    EXPECT_TRUE(RouteFind(agent->fabric_policy_vrf_name(), ip, 0));

    EXPECT_TRUE(RouteFind(agent->fabric_vrf_name(), ip, 0));
    InetUnicastRouteEntry *rt = RouteGet(agent->fabric_vrf_name(), ip, 0);
    const NextHop *nh = rt->GetActiveNextHop();
    EXPECT_TRUE(nh->GetType() == NextHop::COMPOSITE);
    const CompositeNH *comp_nh = static_cast<const CompositeNH *>(nh);
    EXPECT_TRUE(comp_nh->ComponentNHCount() == 2);
    const NextHop *nh1 = comp_nh->GetNH(0);
    const NextHop *nh2 = comp_nh->GetNH(1);
    EXPECT_TRUE(nh1->GetType() == NextHop::ARP);
    EXPECT_TRUE(nh2->GetType() == NextHop::ARP);

    /* Verify both ArpNH are invalid */
    EXPECT_TRUE(nh1->IsValid() == false);
    EXPECT_TRUE(nh2->IsValid() == false);

    SetSeen(eth_name_1_, true, 1);
    SetSeen(eth_name_2_, true, 1);

    /* AddArp for first gw, verify first ArpNH becomes valid */
    AddArp(fabric_gw_ip_1_.to_string().c_str(), "0a:0b:0c:0d:0e:0f",
            eth_name_1_.c_str());
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == true);
    EXPECT_TRUE(nh2->IsValid() == false);

    /* AddArp for second gw, verify second ArpNH becomes valid */
    AddArp(fabric_gw_ip_2_.to_string().c_str(), "0f:0e:0d:0c:0b:0a",
            eth_name_2_.c_str());
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == true);
    EXPECT_TRUE(nh2->IsValid() == true);

    /* Bring first physical intf down, verify first ArpNH becoms invalid */
    vnswif_->Enqueue(new VnswInterfaceListener::Event(
                         VnswInterfaceListener::Event::ADD_INTERFACE,
                         eth_name_1_, 0, 1));
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == false);
    EXPECT_TRUE(nh2->IsValid() == true);

    /* Bring second physical intf down, verify second ArpNH becoms invalid */
    vnswif_->Enqueue(new VnswInterfaceListener::Event(
                         VnswInterfaceListener::Event::ADD_INTERFACE,
                         eth_name_2_, 0, 1));
    client->WaitForIdle();
    EXPECT_TRUE(nh1->IsValid() == false);
    EXPECT_TRUE(nh2->IsValid() == false);

    /* Clear ArpInterfaceState for both physical interface */
    PhysicalInterfaceKey key1(eth_name_1_);
    PhysicalInterface *intf = static_cast<PhysicalInterface *>(
            agent->interface_table()->FindActiveEntry(&key1));
    intf->ClearState(intf->get_table_partition()->parent(),
                     agent->GetArpProto()->interface_table_listener_id());
    client->WaitForIdle();
    PhysicalInterfaceKey key2(eth_name_2_);
    intf = static_cast<PhysicalInterface *>(
            agent->interface_table()->FindActiveEntry(&key2));
    intf->ClearState(intf->get_table_partition()->parent(),
                     agent->GetArpProto()->interface_table_listener_id());
    client->WaitForIdle();
}

int main(int argc, char *argv[]) {
    int ret = 0;
    GETUSERARGS();
    client = TestInit(VNSW_VHOST_L3MH_CONFIG_FILE,
                      ksync_init, true, true, true, 100*1000);
    Agent::GetInstance()->ksync()->VnswInterfaceListenerInit();
    ret = RUN_ALL_TESTS();
    TestShutdown();
    return ret;
}
