/*
 * Copyright (c) 2023 Matvey Kraposhin
 */

#include "base/os.h"
#include "testing/gunit.h"

#include <boost/scoped_array.hpp>
#include <base/logging.h>
#include <base/task_annotations.h>

#include <pugixml/pugixml.hpp>
#include <io/event_manager.h>
#include "http/http_request.h"
#include "http/http_session.h"
#include "http/http_server.h"
#include "http/client/http_client.h"
#include "http/client/http_curl.h"
#include <cmn/agent_cmn.h>
#include <oper/operdb_init.h>
#include <oper/interface_common.h>
#include <pkt/pkt_init.h>
#include <services/services_init.h>
#include <test/test_cmn_util.h>
#include <services/services_sandesh.h>
#include <services/metadata_proxy.h>
#include "pkt/test/test_pkt_util.h"

#include <cstdio>
#include <cstdlib>
extern "C"{
#include <errno.h>
}

#define DEFAULT_VNSW_METADATA_CONFIG_FILE \
"controller/src/vnsw/agent/test/vnswa_metadata_cfg.ini"
#define MAX_WAIT_COUNT 5000
#define BUF_SIZE 8192
#define md_ip4 "169.254.169.254"
#define md_ip6 "fe80::a9fe:a9fe"
#define vm1_ip "ee80::11"
#define vm1_ll_ip "fe80::11"
#define vm1_mac "00:00:00:01:01:01"
#define nova_proxy_mock_port 8775

IpamInfo ipam_info[] = {
    {"ee80::", 32, "ee80::1"}, /* prefix, prefixlen, gw */
};
Ip4Address md_ip4_address(Ip4Address::from_string(md_ip4));

std::string ExecCmd(const std::string& cmd)
{
    char buffer[BUF_SIZE];
    std::string result;
    FILE *pipe = popen(cmd.c_str(), "r");

    if (!pipe) throw std::runtime_error("popen() failed!");

    while (!feof(pipe)) {
        if (fgets(buffer, BUF_SIZE, pipe) != NULL)
            result += buffer;
    }

    int rc = pclose(pipe);

    if (rc == EXIT_SUCCESS) {
        // std::cout << "SUCCESS\n";
    } else {
        result = std::string("");
        // std::cout << "FAILED\n";
    }

    return result;
}

class Metadata6Test : public ::testing::Test {
public:
    void SetUp() {
        ConcurrencyChecker::enable_ = false;  // disable concurrency check
        agent_ = Agent::GetInstance();
        AddIPAM("vn1", ipam_info, 1);
        client->WaitForIdle();

        // Check for a vhost presence
        vhost_was_created_ = false;
        std::string vhost_nm = Agent::GetInstance()->vhost_interface_name();
        std::string vhost_str =
            ExecCmd(std::string("ip a | grep " + vhost_nm));
        // try to create a vhost interface
        if (vhost_str.empty()) {
            vhost_was_created_ = true;
            std::string create_vhost = "ip link add " + vhost_nm +
                " type dummy";
            std::system(create_vhost.c_str());
        }
    }

    void TearDown() {
        DelIPAM("vn1");
        DeleteGlobalVrouterConfig();
        client->WaitForIdle();
        if (vhost_was_created_) {
            std::string vhost_nm =
                Agent::GetInstance()->vhost_interface_name();
            std::string delete_vhost = "ip link del " + vhost_nm +
                " type dummy";
            std::system(delete_vhost.c_str());
        }
    }

    Metadata6Test() {
        Agent::GetInstance()->set_compute_node_ip(
            Ip4Address::from_string("127.0.0.1"));
    }

    ~Metadata6Test() {
    }

    void CheckSandeshResponse(Sandesh *sandesh) {
    }

    void SetupLinkLocalConfig() {
        std::stringstream global_config;
        global_config << "<linklocal-services>\n"
            << "<linklocal-service-entry>\n"
            << "<linklocal-service-name>metadata</linklocal-service-name>\n"
            << "<linklocal-service-ip>"<< md_ip4_address.to_string()
            <<"</linklocal-service-ip>\n"
            << "<linklocal-service-port>80</linklocal-service-port>\n"
            << "<ip-fabric-DNS-service-name></ip-fabric-DNS-service-name>\n"
            << "<ip-fabric-service-port>"
                << nova_proxy_mock_port
                << "</ip-fabric-service-port>\n"
            << "<ip-fabric-service-ip>127.0.0.1</ip-fabric-service-ip>\n"
            << "</linklocal-service-entry>\n"
            << "</linklocal-services>";

        char buf[BUF_SIZE];
        int len = 0;
        memset(buf, 0, BUF_SIZE);
        AddXmlHdr(buf, len);
        AddNodeString(buf, len, "global-vrouter-config",
            "default-global-system-config:default-global-vrouter-config",
            1024, global_config.str().c_str());
        AddXmlTail(buf, len);
        ApplyXmlString(buf);
    }

    void ClearLinkLocalConfig() {
        char buf[BUF_SIZE];
        int len = 0;
        memset(buf, 0, BUF_SIZE);
        AddXmlHdr(buf, len);
        AddNodeString(buf, len, "global-vrouter-config",
            "default-global-system-config:default-global-vrouter-config",
            1024, "");
        AddXmlTail(buf, len);
        ApplyXmlString(buf);
    }

    Agent *agent_;
private:
    bool vhost_was_created_;
};

TEST_F(Metadata6Test, Metadata6RouteFuncsTest) {
    struct PortInfo input[] = {
        /*  name  intf_id ip_addr mac_addr vn_id vm_id ip6addr*/
        {"vnet1", 1,      vm1_ip, vm1_mac, 1,    1},
    };

    SetupLinkLocalConfig();

    CreateV6VmportEnv(input, 1, 0);
    client->WaitForIdle();
    client->Reset();

    VnEntry *vn1 = VnGet(1);
    EXPECT_TRUE(vn1 != NULL);

    VrfEntry *vrf1 = vn1->GetVrf();
    EXPECT_TRUE(vrf1 != NULL);

    InetUnicastRouteEntry *ucrt_vm_ip = vrf1->GetUcRoute
        (boost::asio::ip::address::from_string(vm1_ip));
    InetUnicastRouteEntry *ucrt_md_ip = vrf1->GetUcRoute
        (boost::asio::ip::address::from_string(md_ip6));
    // AnnounceVhostRoute, OnAVrfChange
    EXPECT_TRUE(ucrt_vm_ip != NULL);
    EXPECT_TRUE(ucrt_md_ip != NULL);
    EXPECT_TRUE(ucrt_vm_ip->addr().to_string() == std::string(vm1_ip));
    EXPECT_TRUE(ucrt_md_ip->addr().to_string() == std::string(md_ip6));

    VrfEntry *fabric_vrf = Agent::GetInstance()->fabric_vrf();
    EXPECT_TRUE(fabric_vrf != NULL);

    VmInterface *intf = static_cast<VmInterface *>(VmPortGet(1));

    TxTcp6Packet(intf->id(), vm1_ip, md_ip6, 1000, 80, false);
    client->WaitForIdle();
    FlowEntry *flow = FlowGet(0, vm1_ip, md_ip6, 6, 1000, 80,
                              intf->flow_key_nh()->id());
    EXPECT_TRUE(flow != NULL);
    FlowEntry *rflow = flow->reverse_flow_entry();
    EXPECT_TRUE(rflow != NULL);

    EXPECT_TRUE(flow->key().src_addr.to_v6() ==
                Ip6Address::from_string(vm1_ip));
    EXPECT_TRUE(flow->key().dst_addr.to_v6() ==
                Ip6Address::from_string(md_ip6));
    EXPECT_TRUE(rflow->key().src_addr.to_v6() ==
        Ip6Address::from_string(md_ip6));
    EXPECT_TRUE(rflow->key().dst_addr.to_v6() ==
        Ip6Address::from_string(vm1_ip));

    // Add routes manually (imitation of a packet interception
    // by the PktFlowInfo::IngressProcess)
    IpAddress ll_ip(Ip6Address::from_string(vm1_ll_ip));
    Agent::GetInstance()->services()->metadataproxy()->
        AnnounceMetaDataLinkLocalRoutes(intf, ll_ip.to_v6(), vrf1);
    InetUnicastRouteEntry *ucrt_ll1 = fabric_vrf->GetUcRoute(ll_ip);
    InetUnicastRouteEntry *ucrt_ll2 = vrf1->GetUcRoute(ll_ip);
    EXPECT_TRUE(ucrt_ll1 != NULL);
    EXPECT_TRUE(ucrt_ll2 != NULL);
    EXPECT_TRUE(ucrt_ll1->addr() == ll_ip);  // AnnounceMetaDataLinkLocalRoutes
    EXPECT_TRUE(ucrt_ll2->addr() == ll_ip);  // AnnounceMetaDataLinkLocalRoutes
    // Find the correspondence between ll ip and vm idx
    std::string vm_ip, vm_uuid, vm_project_uuid;
    bool found = Agent::GetInstance()->interface_table()->
        FindVmUuidFromMetadataIp(ll_ip, &vm_ip, &vm_uuid, &vm_project_uuid);
    EXPECT_TRUE(found);  // LinkVmPortToMetaDataIp, FindInterfaceFromMetadataIp
                         // FindVmUuidFromMetadataIp
    EXPECT_EQ(vm_ip, intf->primary_ip6_addr().to_string());
    client->WaitForIdle();

    // Checks: OnAnInterfaceChange, DeleteMetaDataLinkLocalRoute,
    // UnlinkVmPortFromMetaDataIp
    EXPECT_TRUE(Agent::GetInstance()->interface_table()->
        FindInterfaceFromMetadataIp(ll_ip.to_v6()) != NULL);
    DeleteVmportEnv(input, 1, 1, 0);
    client->WaitForIdle();
    EXPECT_TRUE(Agent::GetInstance()->interface_table() != NULL);
    EXPECT_TRUE(Agent::GetInstance()->interface_table()->
        FindInterfaceFromMetadataIp(ll_ip.to_v6()) == NULL);
    ucrt_ll1 = fabric_vrf->GetUcRoute(ll_ip);
    ucrt_ll2 = vrf1->GetUcRoute(ll_ip);
    EXPECT_TRUE(ucrt_ll1 == NULL);
    EXPECT_TRUE(ucrt_ll2 == NULL);
    ucrt_md_ip = vrf1->GetUcRoute
        (boost::asio::ip::address::from_string(md_ip6));
    EXPECT_TRUE(ucrt_md_ip == NULL);  // DeleteVhostRoute / OnAVrfChange

    client->WaitForIdle();
    ClearLinkLocalConfig();
    client->WaitForIdle();
}

TEST_F(Metadata6Test, Metadata6NlReqTest) {
    // int count = 0;
    // MetadataProxy::MetadataStats stats;
    struct PortInfo input[] = {
        /*  name  intf_id ip_addr mac_addr vn_id vm_id ip6addr*/
        {"vnet1", 1,      vm1_ip, vm1_mac, 1,    1},
    };

    SetupLinkLocalConfig();
    client->WaitForIdle();

    const std::string grep_cmd = "grep";
    const std::string ipa_cmd = "ip addr";
    const std::string ipn_cmd = "ip neigh show";
    // Check grep cmd
    {
        int res1 = std::system((grep_cmd + " --help").c_str());
        EXPECT_EQ(res1, 0);
    }
    // Check ip a cmd
    {
        int res1 = std::system(ipa_cmd.c_str());
        EXPECT_EQ(res1, 0);
    }
    client->WaitForIdle();

    // check for presence of a vhost interface
    client->WaitForIdle();
    const std::string vhost_cmd = ipa_cmd + " | " + grep_cmd +
        " " + agent_->vhost_interface_name();
    std::string grep_str = ExecCmd(vhost_cmd);
    EXPECT_FALSE(grep_str.empty());
    client->WaitForIdle();

    // try to add ip to vhost0 interface
    const IpAddress vhost_ip = Agent::GetInstance()->
        services()->metadataproxy()->Ipv6ServiceAddress();
    Agent::GetInstance()->
        services()->metadataproxy()->NetlinkAddVhostIp(vhost_ip);
    const std::string find_vhost_ip = ipa_cmd + " | " + grep_cmd +
        " " + vhost_ip.to_string();
    grep_str = ExecCmd(find_vhost_ip);
    EXPECT_FALSE(grep_str.empty());
    client->WaitForIdle();

    CreateV6VmportEnv(input, 1, 0);
    client->WaitForIdle();
    client->Reset();

    VnEntry *vn1 = VnGet(1);
    EXPECT_TRUE(vn1 != NULL);

    IpAddress ll_ip(Ip6Address::from_string(vm1_ll_ip));
    const uint8_t mac_bytes[] = {0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff};
    MacAddress dev_mac(mac_bytes);
    Agent::GetInstance()->
        services()->metadataproxy()->NetlinkAddVhostNb(ll_ip.to_v6(), dev_mac);
    std::string find_vhost_nb = ipn_cmd + " | " + grep_cmd +
        " " + ll_ip.to_string();
    grep_str = ExecCmd(find_vhost_nb);
    EXPECT_FALSE(grep_str.empty());  // NetlinkAddVhostNb
    client->WaitForIdle();

    // Now, delete added vhost ip record (NetlinkDelVhostIp)
    Agent::GetInstance()->
        services()->metadataproxy()->NetlinkDelVhostIp(vhost_ip);
    grep_str = ExecCmd(find_vhost_ip);
    EXPECT_TRUE(grep_str.empty());  // NetlinkDelVhostIp
    client->WaitForIdle();

    // delete nb
    const std::string delete_nb = "ip neig del " +
        ll_ip.to_string() + " dev " + agent_->vhost_interface_name();
    std::system(delete_nb.c_str());
    grep_str = ExecCmd(find_vhost_nb);
    EXPECT_TRUE(grep_str.empty());
    client->WaitForIdle();

    // Clear the created env
    DeleteVmportEnv(input, 1, 1, 0);
    client->WaitForIdle();

    ClearLinkLocalConfig();
    client->WaitForIdle();
}

TEST_F(Metadata6Test, Metadata6ServerResetTest) {
    struct PortInfo input[] = {
        /*  name  intf_id ip_addr mac_addr vn_id vm_id ip6addr*/
        {"vnet1", 1,      vm1_ip, vm1_mac, 1,    1},
    };
    CreateV6VmportEnv(input, 1, 0);
    client->WaitForIdle();
    client->Reset();
    VnEntry *vn1 = VnGet(1);
    EXPECT_TRUE(vn1 != NULL);
    VrfEntry *vrf1 = vn1->GetVrf();
    EXPECT_TRUE(vrf1 != NULL);

    VrfEntry *fabric_policy_vrf = Agent::GetInstance()->fabric_policy_vrf();
    EXPECT_TRUE(fabric_policy_vrf != NULL);
    InetUnicastAgentRouteTable *fabric_uc =
        fabric_policy_vrf->GetInet4UnicastRouteTable();
    EXPECT_TRUE(fabric_uc);
    // Clear old service config
    ClearLinkLocalConfig();
    client->WaitForIdle();

    // Add config with default address + announce a corresponding route
    SetupLinkLocalConfig();
    client->WaitForIdle();
    {
        // find metadata service and announce a route to vhost0 interface
        uint16_t nova_port, linklocal_port;
        Ip4Address nova_server, linklocal_server;
        std::string nova_hostname;

        if (agent_->oper_db()->global_vrouter()->FindLinkLocalService(
            GlobalVrouter::kMetadataService, &linklocal_server, &linklocal_port,
            &nova_hostname, &nova_server, &nova_port)) {
            fabric_uc->AddInetInterfaceRouteReq
                (Agent::GetInstance()->link_local_peer(),
                Agent::GetInstance()->fabric_policy_vrf_name(),
                md_ip4_address,
                32,
                Agent::GetInstance()->vhost_interface_name(),
                0,
                VnListType());
            client->WaitForIdle();
        }
        EXPECT_TRUE(linklocal_server == md_ip4_address);
    }
    InetUnicastRouteEntry *fabric_md_rt =
        fabric_policy_vrf->GetUcRoute(md_ip4_address);
    EXPECT_TRUE(fabric_md_rt != NULL);
    EXPECT_TRUE(fabric_md_rt->addr().to_string() == md_ip4_address.to_string());

    Ip6Address md_ll_ip6_address(Ip6Address::from_string(md_ip6));
    InetUnicastRouteEntry *ucrt_md = vrf1->GetUcRoute(md_ll_ip6_address);
    EXPECT_TRUE(ucrt_md != NULL);  // AnnounceVhostRoute, OnAVrfChange
    EXPECT_TRUE(
        Agent::GetInstance()->services()->metadataproxy()->Ipv6ServiceAddress()
        == md_ll_ip6_address);
    EXPECT_TRUE(ucrt_md->addr() == md_ll_ip6_address);

    // Change address of Metadata service and update config
    md_ip4_address = Ip4Address::from_string("169.254.254.169");
    md_ll_ip6_address = Ip6Address::from_string("fe80::a9fe:fea9");
    ClearLinkLocalConfig();
    client->WaitForIdle();
    SetupLinkLocalConfig();
    client->WaitForIdle();

    {
        // find metadata service
        uint16_t nova_port, linklocal_port;
        Ip4Address nova_server, linklocal_server;
        std::string nova_hostname;

        if (agent_->oper_db()->global_vrouter()->FindLinkLocalService(
            GlobalVrouter::kMetadataService, &linklocal_server, &linklocal_port,
            &nova_hostname, &nova_server, &nova_port)) {
            // fabric_uc->Delete
            //     (Agent::GetInstance()->link_local_peer(),
            //     Agent::GetInstance()->fabric_policy_vrf_name(),
            //     old_md_ip4_address,
            //     32);

            fabric_uc->AddInetInterfaceRouteReq
                (Agent::GetInstance()->link_local_peer(),
                Agent::GetInstance()->fabric_policy_vrf_name(),
                md_ip4_address,
                32,
                Agent::GetInstance()->vhost_interface_name(),
                0,
                VnListType());
            client->WaitForIdle();
        }
        EXPECT_TRUE(linklocal_server == md_ip4_address);
    }
    fabric_md_rt =
        fabric_policy_vrf->GetUcRoute(md_ip4_address);
    EXPECT_TRUE(fabric_md_rt != NULL);
    EXPECT_TRUE(fabric_md_rt->addr().to_string() == md_ip4_address.to_string());

    ucrt_md = vrf1->GetUcRoute(md_ll_ip6_address);
    EXPECT_TRUE(ucrt_md != NULL);  // AnnounceVhostRoute, OnAVrfChange
    EXPECT_TRUE(
        Agent::GetInstance()->services()->metadataproxy()->Ipv6ServiceAddress()
        == md_ll_ip6_address);
    EXPECT_TRUE(ucrt_md->addr() == md_ll_ip6_address);

    ClearLinkLocalConfig();
    client->WaitForIdle();

    DeleteVmportEnv(input, 1, 1, 0);
    client->WaitForIdle();
}

void RouterIdDepInit(Agent *agent) {
}

int main(int argc, char *argv[]) {
    GETUSERARGS();

    client = TestInit(DEFAULT_VNSW_METADATA_CONFIG_FILE, ksync_init, true,
                        true, false);
    usleep(100000);
    client->WaitForIdle();

    int ret = RUN_ALL_TESTS();
    TestShutdown();
    delete client;
    return ret;
}
