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

#define AGENT_NO_GW_CONFIG_FILE \
        "controller/src/vnsw/agent/init/test/cfg-no-gw.ini"

using namespace boost::assign;

class RouteTest : public ::testing::Test {
public:

protected:
    RouteTest() : vrf_name_("vrf1") {
        agent_ = Agent::GetInstance();
        server2_ip_ = Ip4Address::from_string("10.1.1.10");
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
        WAIT_FOR(100, 1000, (VrfFind(vrf_name_.c_str()) != true));
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
    Ip4Address  server2_ip_;
    Ip4Address  remote_vm_ip_;
    Agent *agent_;
    BgpPeer *bgp_peer_;
};

TEST_F(RouteTest, RemoteVmRoute_5) {
    //Add remote VM route IP, pointing to another compute in same n/w
    AddRemoteVmRoute(remote_vm_ip_, server2_ip_, 32,
                     MplsTable::kStartLabel, TunnelType::AllType());
    EXPECT_TRUE(RouteFind(vrf_name_, remote_vm_ip_, 32));

    //Verify NextHop is TunnelNH
    InetUnicastRouteEntry *addr_rt = RouteGet(vrf_name_, remote_vm_ip_, 32);
    const NextHop *addr_nh = addr_rt->GetActiveNextHop();
    EXPECT_TRUE(addr_nh->GetType() == NextHop::TUNNEL);

    //Delete remote server route
    DeleteRoute(bgp_peer_, vrf_name_, remote_vm_ip_, 32);
    EXPECT_FALSE(RouteFind(vrf_name_, remote_vm_ip_, 32));
}

int main(int argc, char *argv[]) {
    ::testing::InitGoogleTest(&argc, argv);
    GETUSERARGS();
    client = TestInit(AGENT_NO_GW_CONFIG_FILE, ksync_init, true, false);
    int ret = RUN_ALL_TESTS();
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
