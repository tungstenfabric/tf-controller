/*
 * 
 */
#include "base/os.h"
#include <cmn/agent_cmn.h>
#include "vr_types.h"
#include "testing/gunit.h"

#include <oper/agent_route.h>
#include <oper/vrf.h>
#include <oper/inet_unicast_route.h>
#include <oper/evpn_route.h>

#include "test_cmn_util.h"


class FipRoutesLeaking : public ::testing::Test {
public:

    struct InpData{
        struct PortInfo input[2];

        IpamInfo ipam_info1[1];

        IpamInfo ipam_info2[1];
    };
    InpData inp_data;

    const char* domestic_addr;
    const char* foreign_addr;

    FipRoutesLeaking()
    : domestic_addr("1.1.1.2"),
    foreign_addr("2.2.2.2") 
    {
        agent_ = Agent::GetInstance();

        InpData inp_data0 = {
            .input = {
                {"vnet1", 1, "1.1.1.29", "00:00:00:01:01:01", 1, 1},
                {"vnet2", 2, "1.1.1.29", "00:00:00:01:01:01", 1, 2}},
            .ipam_info1 = {
                {"1.1.1.0", 24, "1.1.1.1"}},
            .ipam_info2= {
                {"2.2.2.0", 24, "2.2.2.1"}}
        };
        this->inp_data = inp_data0;
    }

    virtual ~FipRoutesLeaking() {

    }

    virtual void SetUp() {
        ////////////////////////////////////////////////////////////

        //see void AddVmPort for hints
        struct PortInfo (&input)[2] = inp_data.input;
        struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;
        client->WaitForIdle();
        client->Reset();
        AddVm("vm1", 1);
        AddVm("vm2", 2);
        AddVrf("vrf1");
        AddVn("vn1", 1);

        AddPort(input[0].name, input[0].intf_id); //vnet1
        AddPort(input[1].name, input[1].intf_id); //vnet2
        AddVmPortVrf("vmvrf1_1", "", 0); // 0 is a tag
        AddVmPortVrf("vmvrf1_2", "", 0); // 0 is a tag
        AddIPAM("vn1", ipam_info1, 1);
        IntfCfgAdd(input, 0); //0 - this is a position in input[]
        IntfCfgAdd(input, 1); //1 - this is a position in input[]
        AddActiveActiveInstanceIp("instance1", 1, input[0].addr);
        client->WaitForIdle();

        AddLink("virtual-network", "vn1", "routing-instance", "vrf1");
        AddLink("virtual-network", "vn1", "instance-ip", "instance1");
        //////// Links to the port "vnet1"
        AddLink("virtual-machine-interface-routing-instance", "vmvrf1_1",
                "routing-instance", "vrf1");
        AddLink("virtual-machine-interface-routing-instance", "vmvrf1_1",
            "virtual-machine-interface", input[0].name);
        AddLink("virtual-network", "vn1", "virtual-machine-interface", input[0].name);
        AddLink("virtual-machine", "vm1", "virtual-machine-interface", input[0].name);
        AddLink("virtual-machine-interface", input[0].name,
                "instance-ip", "instance1");
        //////// Links to the port "vnet2"
        AddLink("virtual-machine-interface-routing-instance", "vmvrf1_2",
                "routing-instance", "vrf1");
        AddLink("virtual-machine-interface-routing-instance", "vmvrf1_2",
            "virtual-machine-interface", input[1].name);
        AddLink("virtual-network", "vn1", "virtual-machine-interface", input[1].name);
        AddLink("virtual-machine", "vm1", "virtual-machine-interface", input[1].name);
        AddLink("virtual-machine-interface", input[1].name,
                "instance-ip", "instance1");
        client->WaitForIdle();
    }

    virtual void TearDown() {
        struct PortInfo (&input)[2] = inp_data.input;
        struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;

        client->WaitForIdle();
        
        DelLink("virtual-machine-interface", input[1].name,
                "instance-ip", "instance1");
        DelLink("virtual-machine", "vm1", "virtual-machine-interface", input[1].name);
        DelLink("virtual-network", "vn1", "virtual-machine-interface", input[1].name);
        DelLink("virtual-machine-interface-routing-instance", "vmvrf1_2",
            "virtual-machine-interface", input[1].name);
        DelLink("virtual-machine-interface-routing-instance", "vmvrf1_2",
                "routing-instance", "vrf1");
        
        DelLink("virtual-machine-interface", input[0].name,
                "instance-ip", "instance1");
        DelLink("virtual-machine", "vm1", "virtual-machine-interface", input[0].name);
        DelLink("virtual-network", "vn1", "virtual-machine-interface", input[0].name);
        DelLink("virtual-machine-interface-routing-instance", "vmvrf1_1",
            "virtual-machine-interface", input[0].name);
        DelLink("virtual-machine-interface-routing-instance", "vmvrf1_1",
                "routing-instance", "vrf1");
        
        DelLink("virtual-network", "vn1", "instance-ip", "instance1");
        DelLink("virtual-network", "vn1", "routing-instance", "vrf1");

        client->WaitForIdle();
        
        DelInstanceIp("instance1");
        IntfCfgDel(input, 1);
        IntfCfgDel(input, 0); //0 - this is a position in input[]
        DelIPAM("vn1");
        DelVmPortVrf("vmvrf1_2");
        DelVmPortVrf("vmvrf1_1");
        DelPort(input[1].name); //vnet2
        DelPort(input[0].name);

        DelVn("vn1");
        DelVrf("vrf1");
        DelVm("vm2");
        DelVm("vm1");

        client->WaitForIdle();
    }

    void print_table_routes(AgentRoute* c_route) {
        const Route::PathList & path_list = c_route->GetPathList();
        for(Route::PathList::const_iterator it = path_list.begin();
            it != path_list.end(); ++it) {
                const AgentPath* path = dynamic_cast<const AgentPath*>(it.operator->());
                std::cout << "NH: " << (path->nexthop() ? path->nexthop()->ToString() : "NULL") << ", "
                        << "Peer:" << (path->peer() ? path->peer()->GetName() : "NULL") << std::endl;
        }
    }

    void print_vrf_tables(VrfEntry* vrf) {
        std::cout << "Inet4 table" << std::endl;
        InetUnicastAgentRouteTable* c_inet_tbl = 
            vrf->GetInet4UnicastRouteTable();
        int n_part = c_inet_tbl->PartitionCount();
        
        for (int i_part=0; i_part < n_part; i_part++) {
            InetUnicastRouteEntry* c_route = 
                dynamic_cast<InetUnicastRouteEntry*> 
                (c_inet_tbl->GetTablePartition(i_part)->GetFirst());
            while (c_route) {
                std::cout<< "IP:" << c_route->addr() << std::endl;
                this->print_table_routes(c_route);
                c_route = dynamic_cast<InetUnicastRouteEntry*>
                    (c_inet_tbl->GetTablePartition(i_part)->GetNext(c_route));
            }
        }

        std::cout << "Evpn table" << std::endl;
        EvpnAgentRouteTable* c_evpn_tbl =
            dynamic_cast<EvpnAgentRouteTable*>
            (vrf->GetEvpnRouteTable());
        n_part = c_evpn_tbl->PartitionCount();
        
        for (int i_part=0; i_part < n_part; i_part++) {
            EvpnRouteEntry* c_route = 
                dynamic_cast<EvpnRouteEntry*> 
                (c_evpn_tbl->GetTablePartition(i_part)->GetFirst());
            while (c_route) {
                std::cout<< "IP:" << c_route->ip_addr() << ", "
                         << "MAC:"<< c_route->mac().ToString() << ", "
                         << "PLEN:"<< c_route->GetVmIpPlen() << ", "
                         << "ETAG:"<< c_route->ethernet_tag()
                         << std::endl;
                this->print_table_routes(c_route);
                c_route = dynamic_cast<EvpnRouteEntry*>
                    (c_evpn_tbl->GetTablePartition(i_part)->GetNext(c_route));
            }
        }
    }

    void print_agent_vrfs() {
        VrfTable* vrf_table = agent_->vrf_table();
        int n_part = vrf_table->PartitionCount();
        
        for (int i_part=0; i_part < n_part; i_part++) {
            VrfEntry* c_vrf = dynamic_cast<VrfEntry*>
                (vrf_table->GetTablePartition(i_part)->GetFirst());
            while (c_vrf) {
                std::cout << "Vrf:" << c_vrf->GetName() << std::endl;
                this->print_vrf_tables(c_vrf);
                c_vrf = dynamic_cast<VrfEntry*>
                    (vrf_table->GetTablePartition(i_part)->GetNext(c_vrf));
            }
        }
    }

protected:

    Agent *agent_;
};

TEST_F(FipRoutesLeaking, fip_test_initial_conf) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;

    AddFloatingIp("fip1", 1, domestic_addr,  input[0].addr, "INGRESS", true, 80);

    AddLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    AddLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    AddLink("floating-ip", "fip1", "instance-ip", "instance1");
    client->WaitForIdle();

    //print_agent_vrfs();

    //Check link with the first interface
    VmInterface *vmi1 = static_cast<VmInterface *>(VmPortGet(1));
    EXPECT_TRUE(vmi1);
    const VmInterface::FloatingIpSet &fip_list1 =
        vmi1->floating_ip_list().list_;
    EXPECT_EQ(fip_list1.size(), 1);

    //Check link with the second interface
    VmInterface *vmi2 = static_cast<VmInterface *>(VmPortGet(2));
    EXPECT_TRUE(vmi2);
    const VmInterface::FloatingIpSet &fip_list2 =
        vmi2->floating_ip_list().list_;
    EXPECT_EQ(fip_list2.size(), 1);

    DelLink("floating-ip", "fip1", "instance-ip", "instance1");
    DelLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    DelLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");

    DelFloatingIp("fip1");
}

TEST_F(FipRoutesLeaking, fip_test_two_vrf) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;
    struct IpamInfo (&ipam_info2)[1] = inp_data.ipam_info2;

    AddVrf("vrf2");
    AddVn("vn2", 2);
    AddVmPortVrf("vmvrf2_1", "", 0); // 0 is a tag
    AddVmPortVrf("vmvrf2_2", "", 0); // 0 is a tag
    AddIPAM("vn2", ipam_info2, 1);
    AddActiveActiveInstanceIp("instance2", 2, foreign_addr);

    AddLink("virtual-network", "vn2", "routing-instance", "vrf2");
    AddLink("virtual-network", "vn2", "instance-ip", "instance2");

    //Ports are present, let's just connect them to a new
    //ip instance
    //vnet1
    AddLink("virtual-machine-interface-routing-instance", "vmvrf2_1",
            "routing-instance", "vrf2");
    AddLink("virtual-machine-interface-routing-instance", "vmvrf2_1",
        "virtual-machine-interface", input[0].name);
    AddLink("virtual-network", "vn2", "virtual-machine-interface", input[0].name);
    AddLink("virtual-machine-interface", input[0].name,
            "instance-ip", "instance2");
    //vnet2
    AddLink("virtual-machine-interface-routing-instance", "vmvrf2_2",
            "routing-instance", "vrf2");
    AddLink("virtual-machine-interface-routing-instance", "vmvrf2_2",
        "virtual-machine-interface", input[1].name);
    AddLink("virtual-network", "vn2", "virtual-machine-interface", input[1].name);
    AddLink("virtual-machine-interface", input[1].name,
            "instance-ip", "instance2");
    client->WaitForIdle();

    //print_agent_vrfs();

    //Check that Inet and Evpn tables of a new vrf contain
    //routes for a given prefix "foreign_addr"
    VrfEntry* vrf2 = VrfGet("vrf2");
    EXPECT_TRUE (vrf2);

    InetUnicastAgentRouteTable *inet_table =
        vrf2->GetInet4UnicastRouteTable();
    EXPECT_TRUE(inet_table);

    IpAddress wanted_prefix = boost::asio::ip::address::
        from_string(std::string(foreign_addr));
    InetUnicastRouteEntry* inet_rt =
        inet_table->FindRoute(wanted_prefix);
    EXPECT_TRUE(inet_rt);

    EvpnAgentRouteTable* evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>
        (vrf2->GetEvpnRouteTable());
    MacAddress wanted_mac1 =
        MacAddress::FromString(std::string(input[0].mac));

    EvpnRouteEntry* evpn_rt =
        evpn_table->FindRoute(
            wanted_mac1,
            wanted_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EXPECT_TRUE(evpn_rt);

    client->WaitForIdle();

    DelLink("virtual-machine-interface", input[0].name,
            "instance-ip", "instance2");
    DelLink("virtual-network", "vn2", "virtual-machine-interface", input[0].name);
    DelLink("virtual-machine-interface-routing-instance", "vmvrf2_1",
        "virtual-machine-interface", input[0].name);
    DelLink("virtual-machine-interface-routing-instance", "vmvrf2_1",
            "routing-instance", "vrf2");

    DelLink("virtual-machine-interface", input[1].name,
            "instance-ip", "instance2");
    DelLink("virtual-network", "vn2", "virtual-machine-interface", input[1].name);
    DelLink("virtual-machine-interface-routing-instance", "vmvrf2_2",
        "virtual-machine-interface", input[1].name);
    DelLink("virtual-machine-interface-routing-instance", "vmvrf2_2",
            "routing-instance", "vrf2");

    DelLink("virtual-network", "vn2", "instance-ip", "instance2");
    DelLink("virtual-network", "vn2", "routing-instance", "vrf2");

    DelInstanceIp("instance2");
    DelIPAM("vn2");
    DelVmPortVrf("vmvrf2_2");
    DelVmPortVrf("vmvrf2_1");
    DelVn("vn2");
    DelVrf("vrf2");
}

TEST_F(FipRoutesLeaking, fip_test_add_fip) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;
    struct IpamInfo (&ipam_info2)[1] = inp_data.ipam_info2;

    AddVrf("vrf2");
    AddVn("vn2", 2);
    AddIPAM("vn2", ipam_info2, 1);
    AddActiveActiveInstanceIp("instance2", 1, foreign_addr);

    AddLink("virtual-network", "vn2", "routing-instance", "vrf2");
    AddLink("virtual-network", "vn2", "instance-ip", "instance2");

    //Ports are present, let's just create FIP w/ IIP attached
    //to it
    AddFloatingIp("fip1", 1, foreign_addr,  input[0].addr, "BOTH", true, 80);    
    AddLink("floating-ip", "fip1", "instance-ip", "instance2");

    AddLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    AddLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");

    client->WaitForIdle();

    //print_agent_vrfs();

    //Check that Inet and Evpn tables of a new vrf contain
    //routes for a given prefix "foreign_addr"
    VrfEntry* vrf2 = VrfGet("vrf2");
    EXPECT_TRUE (vrf2);

    InetUnicastAgentRouteTable *inet_table =
        vrf2->GetInet4UnicastRouteTable();
    EXPECT_TRUE(inet_table);

    IpAddress wanted_prefix = boost::asio::ip::address::
        from_string(std::string(foreign_addr));
    InetUnicastRouteEntry* inet_rt =
        inet_table->FindRoute(wanted_prefix);
    EXPECT_TRUE(inet_rt);

    EvpnAgentRouteTable* evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>
        (vrf2->GetEvpnRouteTable());
    MacAddress wanted_mac1 =
        MacAddress::FromString(std::string(input[0].mac));

    EvpnRouteEntry* evpn_rt =
        evpn_table->FindRoute(
            wanted_mac1,
            wanted_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EXPECT_TRUE(evpn_rt);

    client->WaitForIdle();

    DelLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    DelLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    DelLink("floating-ip", "fip1", "instance-ip", "instance2");

    DelFloatingIp("fip1");

    DelLink("virtual-network", "vn2", "instance-ip", "instance2");
    DelLink("virtual-network", "vn2", "routing-instance", "vrf2");

    DelInstanceIp("instance2");
    DelIPAM("vn2");
    DelVn("vn2");
    DelVrf("vrf2");
}

//test with "BOTH" direction 
TEST_F(FipRoutesLeaking, fip_test_initial_conf_with_lr1) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;

    AddLrVmiPort("lr-vmi-vn1", 101, "1.1.1.101", "vrf1", "vn1",
        "instance_ip_1", 1);
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    client->WaitForIdle();

    AddFloatingIp("fip1", 1, domestic_addr,  input[0].addr, "BOTH", true, 80);
    AddLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    AddLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    AddLink("floating-ip", "fip1", "instance-ip", "instance1");
    client->WaitForIdle();

    //print_agent_vrfs();

    //Check link with the first interface
    VmInterface *vmi1 = static_cast<VmInterface *>(VmPortGet(1));
    EXPECT_TRUE(vmi1);
    const VmInterface::FloatingIpSet &fip_list1 =
        vmi1->floating_ip_list().list_;
    EXPECT_EQ(fip_list1.size(), 1);

    //Check link with the second interface
    VmInterface *vmi2 = static_cast<VmInterface *>(VmPortGet(2));
    EXPECT_TRUE(vmi2);
    const VmInterface::FloatingIpSet &fip_list2 =
        vmi2->floating_ip_list().list_;
    EXPECT_EQ(fip_list2.size(), 1);

    //Check that Inet and Evpn tables of the l3vrf contain
    //routes for a given prefix "domestic_addr"
    VrfEntry* l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf);

    InetUnicastAgentRouteTable *inet_table =
        l3vrf->GetInet4UnicastRouteTable();
    EXPECT_TRUE(inet_table);

    IpAddress wanted_fip_prefix = boost::asio::ip::address::
        from_string(std::string(domestic_addr));
    IpAddress wanted_int_prefix = boost::asio::ip::address::
        from_string(std::string(input[0].addr));
    InetUnicastRouteEntry* inet_rt =
        inet_table->FindRoute(wanted_fip_prefix);
    InetUnicastRouteEntry* inet_rt2 =
        inet_table->FindRoute(wanted_int_prefix);
    EXPECT_TRUE(inet_rt);
    EXPECT_TRUE(inet_rt2);

    EvpnAgentRouteTable* evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>
        (l3vrf->GetEvpnRouteTable());
    EXPECT_TRUE(evpn_table);
    EvpnRouteEntry* evpn_rt =
        evpn_table->FindRoute(
            MacAddress(),    // MAC is zero after route leaking
            wanted_fip_prefix,
            inet_rt->plen(),
            0  // ethernet tag is zero for Type5
        );
    EvpnRouteEntry* evpn_rt2 =
        evpn_table->FindRoute(
            MacAddress(),    // MAC is zero after route leaking
            wanted_int_prefix,
            inet_rt->plen(),
            0  // ethernet tag is zero for Type5
        );
    EXPECT_TRUE(evpn_rt);
    EXPECT_TRUE(evpn_rt2);

    DelLink("floating-ip", "fip1", "instance-ip", "instance1");
    DelLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    DelLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    DelFloatingIp("fip1");

    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
    //DeleteBgpPeer(bgp_peer);
    DelLrVmiPort("lr-vmi-vn1", 101, "1.1.1.101", "vrf1", "vn1",
        "instance_ip_1", 1);

    //Check that corresponding objects were deleted
    l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf == NULL);
    EXPECT_EQ(fip_list1.size(), 0);
    EXPECT_EQ(fip_list2.size(), 0);
}

//test with "INGRESS" direction 
TEST_F(FipRoutesLeaking, fip_test_initial_conf_with_lr2) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;

    AddLrVmiPort("lr-vmi-vn1", 101, "1.1.1.101", "vrf1", "vn1",
        "instance_ip_1", 1);
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    client->WaitForIdle();

    AddFloatingIp("fip1", 1, domestic_addr,  input[0].addr, "INGRESS", true, 80);
    AddLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    AddLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    AddLink("floating-ip", "fip1", "instance-ip", "instance1");
    client->WaitForIdle();

    //print_agent_vrfs();

    //Check link with the first interface
    VmInterface *vmi1 = static_cast<VmInterface *>(VmPortGet(1));
    EXPECT_TRUE(vmi1);
    const VmInterface::FloatingIpSet &fip_list1 =
        vmi1->floating_ip_list().list_;
    EXPECT_EQ(fip_list1.size(), 1);

    //Check link with the second interface
    VmInterface *vmi2 = static_cast<VmInterface *>(VmPortGet(2));
    EXPECT_TRUE(vmi2);
    const VmInterface::FloatingIpSet &fip_list2 =
        vmi2->floating_ip_list().list_;
    EXPECT_EQ(fip_list2.size(), 1);

    //Check that Inet and Evpn tables of the l3vrf contain
    //routes for a given prefix "domestic_addr"
    VrfEntry* l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf);

    InetUnicastAgentRouteTable *inet_table =
        l3vrf->GetInet4UnicastRouteTable();
    EXPECT_TRUE(inet_table);

    IpAddress wanted_fip_prefix = boost::asio::ip::address::
        from_string(std::string(domestic_addr));
    IpAddress wanted_int_prefix = boost::asio::ip::address::
        from_string(std::string(input[0].addr));
    InetUnicastRouteEntry* inet_rt =
        inet_table->FindRoute(wanted_fip_prefix);
    InetUnicastRouteEntry* inet_rt2 =
        inet_table->FindRoute(wanted_int_prefix);
    EXPECT_TRUE(inet_rt);
    EXPECT_TRUE(inet_rt2);

    EvpnAgentRouteTable* evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>
        (l3vrf->GetEvpnRouteTable());
    EXPECT_TRUE(evpn_table);
    EvpnRouteEntry* evpn_rt =
        evpn_table->FindRoute(
            MacAddress(),    //MAC is zero after route leaking
            wanted_fip_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EvpnRouteEntry* evpn_rt2 =
        evpn_table->FindRoute(
            MacAddress(),    //MAC is zero after route leaking
            wanted_int_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EXPECT_TRUE(evpn_rt);
    EXPECT_TRUE(evpn_rt2);

    DelLink("floating-ip", "fip1", "instance-ip", "instance1");
    DelLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    DelLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    DelFloatingIp("fip1");

    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
    //DeleteBgpPeer(bgp_peer);
    DelLrVmiPort("lr-vmi-vn1", 101, "1.1.1.101", "vrf1", "vn1",
        "instance_ip_1", 1);

    //Check that corresponding objects were deleted
    l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf == NULL);
    EXPECT_EQ(fip_list1.size(), 0);
    EXPECT_EQ(fip_list2.size(), 0);
}

//test with "EGRESS" direction 
TEST_F(FipRoutesLeaking, fip_test_initial_conf_with_lr3) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info1)[1] = inp_data.ipam_info1;

    AddLrVmiPort("lr-vmi-vn1", 101, "1.1.1.101", "vrf1", "vn1",
        "instance_ip_1", 1);
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    client->WaitForIdle();

    AddFloatingIp("fip1", 1, domestic_addr,  input[0].addr, "EGRESS", true, 80);
    AddLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    AddLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    AddLink("floating-ip", "fip1", "instance-ip", "instance1");
    client->WaitForIdle();

    //print_agent_vrfs();

    //Check link with the first interface
    VmInterface *vmi1 = static_cast<VmInterface *>(VmPortGet(1));
    EXPECT_TRUE(vmi1);
    const VmInterface::FloatingIpSet &fip_list1 =
        vmi1->floating_ip_list().list_;
    EXPECT_EQ(fip_list1.size(), 1);

    //Check link with the second interface
    VmInterface *vmi2 = static_cast<VmInterface *>(VmPortGet(2));
    EXPECT_TRUE(vmi2);
    const VmInterface::FloatingIpSet &fip_list2 =
        vmi2->floating_ip_list().list_;
    EXPECT_EQ(fip_list2.size(), 1);

    //Check that Inet and Evpn tables of the l3vrf contain
    //routes for a given prefix "domestic_addr"
    VrfEntry* l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf);

    InetUnicastAgentRouteTable *inet_table =
        l3vrf->GetInet4UnicastRouteTable();
    EXPECT_TRUE(inet_table);

    IpAddress wanted_fip_prefix = boost::asio::ip::address::
        from_string(std::string(domestic_addr));
    IpAddress wanted_int_prefix = boost::asio::ip::address::
        from_string(std::string(input[0].addr));
    InetUnicastRouteEntry* inet_rt =
        inet_table->FindRoute(wanted_fip_prefix);
    InetUnicastRouteEntry* inet_rt2 =
        inet_table->FindRoute(wanted_int_prefix);
    EXPECT_TRUE(inet_rt);
    EXPECT_TRUE(inet_rt2);

    EvpnAgentRouteTable* evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>
        (l3vrf->GetEvpnRouteTable());
    EXPECT_TRUE(evpn_table);
    EvpnRouteEntry* evpn_rt =
        evpn_table->FindRoute(
            MacAddress(),    // MAC is zero after route leaking
            wanted_fip_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EvpnRouteEntry* evpn_rt2 =
        evpn_table->FindRoute(
            MacAddress(),    // MAC is zero after route leaking
            wanted_int_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EXPECT_TRUE(evpn_rt);
    EXPECT_TRUE(evpn_rt2);

    DelLink("floating-ip", "fip1", "instance-ip", "instance1");
    DelLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    DelLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    DelFloatingIp("fip1");

    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
    //DeleteBgpPeer(bgp_peer);
    DelLrVmiPort("lr-vmi-vn1", 101, "1.1.1.101", "vrf1", "vn1",
        "instance_ip_1", 1);

    //Check that corresponding objects were deleted
    l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf == NULL);
    EXPECT_EQ(fip_list1.size(), 0);
    EXPECT_EQ(fip_list2.size(), 0);
}

//test with "BOTH" direction and 2 vrfs 
TEST_F(FipRoutesLeaking, fip_test_2vrf_conf_with_lr1) {
    struct PortInfo (&input)[2] = inp_data.input;
    struct IpamInfo (&ipam_info2)[1] = inp_data.ipam_info2;

    AddVrf("vrf2");
    AddVn("vn2", 2);
    AddIPAM("vn2", ipam_info2, 1);
    AddActiveActiveInstanceIp("instance2", 2, foreign_addr);

    AddLink("virtual-network", "vn2", "routing-instance", "vrf2");
    AddLink("virtual-network", "vn2", "instance-ip", "instance2");

    AddLrVmiPort("lr-vmi-vn2", 101, "2.2.2.101", "vrf2", "vn2",
                    "instance_ip_2", 2);
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn2", 1);
    client->WaitForIdle();

    AddFloatingIp("fip1", 1, foreign_addr,  input[0].addr, "BOTH", true, 80);
    AddLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    AddLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    AddLink("floating-ip", "fip1", "instance-ip", "instance2");
    client->WaitForIdle();

    //print_agent_vrfs();

    //Check link with the first interface
    VmInterface *vmi1 = static_cast<VmInterface *>(VmPortGet(1));
    EXPECT_TRUE(vmi1);
    const VmInterface::FloatingIpSet &fip_list1 =
        vmi1->floating_ip_list().list_;
    EXPECT_EQ(fip_list1.size(), 1);

    //Check link with the second interface
    VmInterface *vmi2 = static_cast<VmInterface *>(VmPortGet(2));
    EXPECT_TRUE(vmi2);
    const VmInterface::FloatingIpSet &fip_list2 =
        vmi2->floating_ip_list().list_;
    EXPECT_EQ(fip_list2.size(), 1);

    //Check that Inet and Evpn tables of the l3vrf contain
    //routes for a given prefix "domestic_addr"
    VrfEntry* l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf);

    InetUnicastAgentRouteTable *inet_table =
        l3vrf->GetInet4UnicastRouteTable();
    EXPECT_TRUE(inet_table);

    IpAddress wanted_fip_prefix = boost::asio::ip::address::
        from_string(std::string(foreign_addr));
    IpAddress wanted_int_prefix = boost::asio::ip::address::
        from_string(std::string(input[0].addr));
    InetUnicastRouteEntry* inet_rt =
        inet_table->FindRoute(wanted_fip_prefix);
    InetUnicastRouteEntry* inet_rt2 =
        inet_table->FindRoute(wanted_int_prefix);
    EXPECT_TRUE(inet_rt);
    EXPECT_TRUE(inet_rt2 == NULL);

    EvpnAgentRouteTable* evpn_table =
        dynamic_cast<EvpnAgentRouteTable*>
        (l3vrf->GetEvpnRouteTable());
    EXPECT_TRUE(evpn_table);
    EvpnRouteEntry* evpn_rt =
        evpn_table->FindRoute(
            MacAddress(),    // MAC is zero after route leaking
            wanted_fip_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EvpnRouteEntry* evpn_rt2 =
        evpn_table->FindRoute(
            MacAddress(),    //MAC is zero after route leaking
            wanted_int_prefix,
            inet_rt->plen(),
            0   // ethernet tag is zero for Type5
        );
    EXPECT_TRUE(evpn_rt);
    EXPECT_TRUE(evpn_rt2 == NULL);

    DelLink("floating-ip", "fip1", "instance-ip", "instance2");
    DelLink("virtual-machine-interface", input[1].name, "floating-ip", "fip1");
    DelLink("virtual-machine-interface", input[0].name, "floating-ip", "fip1");
    DelFloatingIp("fip1");

    DelLrBridgeVrf("vn2", 1);
    DelLrRoutingVrf(1);
    // //DeleteBgpPeer(bgp_peer);
    DelLrVmiPort("lr-vmi-vn2", 101, "2.2.2.101", "vrf2", "vn2",
                    "instance_ip_2", 2);
    
    DelLink("virtual-network", "vn2", "routing-instance", "vrf2");
    DelLink("virtual-network", "vn2", "instance-ip", "instance2");
    
    DelInstanceIp("instance2");
    DelIPAM("vn2");
    DelVn("vn2");
    DelVrf("vrf2");

    //Check that corresponding objects were deleted
    l3vrf = VrfGet("l3evpn_1");
    EXPECT_TRUE (l3vrf == NULL);
    EXPECT_EQ(fip_list1.size(), 0);
    EXPECT_EQ(fip_list2.size(), 0);
}

int main(int argc, char *argv[]) {
    GETUSERARGS();
    client = TestInit(init_file, ksync_init, true, true, false);

    int ret = RUN_ALL_TESTS();
    TestShutdown();
    delete client;
    return ret;
}

