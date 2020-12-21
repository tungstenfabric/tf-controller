/*
 * Copyright (c) 2015 Juniper Networks, Inc. All rights reserved.
 */

#include <boost/filesystem.hpp>
#include <boost/foreach.hpp>
#include "base/os.h"
#include "testing/gunit.h"
#include "test/test_cmn_util.h"
#include "port_ipc/port_ipc_handler.h"
#include "port_ipc/port_subscribe_table.h"

#define vmi1_mac "00:00:00:00:00:01"
#define vmi2_mac "00:00:00:00:00:02"
#define vmi3_mac "00:00:00:00:00:03"

#define vmi1_ip "11.1.1.1"
#define vmi2_ip "11.1.1.2"
#define vmi3_ip "12.1.1.1"

using namespace std;
namespace fs = boost::filesystem;

struct PortInfo input1[] = {
    {"vmi1", 1, vmi1_ip, vmi1_mac, 1, 1},
};

IpamInfo ipam_info1[] = {
    {"11.1.1.0", 24, "11.1.1.10"},
};

IpamInfo fip_ipam_info[] = {
    {"100.1.1.0", 24, "100.1.1.1"},
};

void RouterIdDepInit(Agent *agent) {
}

class PortIpcTest : public ::testing::Test {
    public:
        PortIpcTest() : agent_(Agent::GetInstance()) {
        }

        Agent *agent() { return agent_; }

        virtual void SetUp() {
            pih_ = agent_->port_ipc_handler();
            // Create virtual-networks
            AddVn("vn1", 1);
            AddIPAM("vn1", ipam_info1, 1);
            AddVrf("vrf1");
            client->WaitForIdle();
            CreateVmportWithoutNova(input1, 1, 1, "vn1", "vrf1");
            client->WaitForIdle();

            EXPECT_EQ(1U, agent_->vm_table()->Size());
            EXPECT_EQ(1U, agent_->vn_table()->Size());
            VnEntry *vn1_ = VnGet(1);
            EXPECT_TRUE(vn1_ != NULL);
        }

        virtual void TearDown() {
            client->Reset();
            DelIPAM("vn1");
            client->WaitForIdle();
            DeleteVmportEnv(input1, 1, true, 1);
            client->WaitForIdle();

            EXPECT_FALSE(VmPortFind(input1, 0));

            EXPECT_EQ(0U, agent_->vm_table()->Size());
            EXPECT_EQ(0U, agent_->vn_table()->Size());
            client->WaitForIdle();
        }

        bool AddVmVnPort(const char *vmi_uuid, const char *vm_id,
                const char *vm_uuid,const char * vm_ifname,
                const char *vn_uuid, const char *vm_namespace,
                const char *vm_name, const char *host_ifname,
                uint8_t vhostuser_mode,
                const char *vhostsocket_dir, const char *vhostsocket_filename) {
            return VmVnPortSubscribe(host_ifname,
                    StringToUuid(vmi_uuid),
                    StringToUuid(vm_uuid),
                    vm_id,
                    vm_name,
                    vm_ifname,
                    vm_namespace,
                    StringToUuid(vn_uuid),
                    vhostuser_mode,
                    vhostsocket_dir,
                    vhostsocket_filename);

        }

        void Sync() {
            pih_->SyncHandler();
        }

        bool IsUUID(const string &file) {
            return pih_->IsUUID(file);
        }

    protected:
        Agent *agent_;
        PortIpcHandler *pih_;
};
static bool GetTestStringMember(const contrail_rapidjson::Value &d, const char *member,
        std::string *data, std::string *err) {
    if (!d.HasMember(member) || !d[member].IsString()) {
        if (err) {
            *err += "Invalid or missing field for <" + string(member) + ">";
        }
        return false;
    }

    *data = d[member].GetString();
    return true;

}

/* Add/delete a port */
TEST_F(PortIpcTest, VmVn_Port_Add_Del) {

    uint32_t port_count = PortSubscribeSize(agent_);
    std::string err_str;
    std::string cfgport_info;
    std::string info;

    /*  GetVmVnCfgPort is called from CNI via REST API  */
    pih_->GetVmVnCfgPort("vm1",cfgport_info);

    /*  AddVmVnPort is called from CNI Port Add via REST API
     *  GetVmVnCfgPort returns id, vm-uuid and vn-id as
     *  00000000-0000-0000-0000-000000000001 for this test case */
    AddVmVnPort("00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000001",
            "net1",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000000",
            "vm1", "vhostnet1-d8ecb0f70603",
            0,
            "/var/run/vrouter/c1aeb007-e09f-4051-962d-4587a75e6265/",
            "d8ecb0f70603-net1");

    client->WaitForIdle(30);
    InterfaceConstRef vmi_ref =
        agent_->interface_table()->FindVmi(StringToUuid("00000000-0000-0000-0000-000000000001"));
    const VmInterface *vmi = dynamic_cast<const VmInterface *>(vmi_ref.get());
    assert(vmi);
    EXPECT_EQ(vmi->vhostsocket_filename(), "d8ecb0f70603-net1");
    EXPECT_EQ(vmi->vhostsocket_dir(), "/var/run/vrouter/c1aeb007-e09f-4051-962d-4587a75e6265/" );
    /* GetVmVnPort is called from CNI via REST API */
    pih_->GetVmVnPort("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001", info);
    //cout << "GetPortInfo for vmi1 O/P" << ":" <<  info << "\n";
    client->WaitForIdle(10);

    assert(info.find("vhostnet1-d8ecb0f70603"));

    pih_->DeleteVmVnPort(StringToUuid("00000000-0000-0000-0000-000000000001"),
            err_str);
    client->WaitForIdle(2);
}

/* Add/delete a port */
TEST_F(PortIpcTest, VmVn_Port_Add_Del_NoDirAndFilename) {

    uint32_t port_count = PortSubscribeSize(agent_);
    std::string err_str;
    std::string cfgport_info;
    std::string info;

    /*  GetVmVnCfgPort is called from CNI via REST API  */
    pih_->GetVmVnCfgPort("vm1",cfgport_info);

    /*  AddVmVnPort is called from CNI Port Add via REST API
     *  GetVmVnCfgPort returns id, vm-uuid and vn-id as
     *  00000000-0000-0000-0000-000000000001 for this test case */
    AddVmVnPort("00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000001",
            "net1",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000000",
            "vm1", "vhostnet1-000000000001",
            0,
            "", "");

    client->WaitForIdle(30);
    InterfaceConstRef vmi_ref =
        agent_->interface_table()->FindVmi(StringToUuid("00000000-0000-0000-0000-000000000001"));
    const VmInterface *vmi = dynamic_cast<const VmInterface *>(vmi_ref.get());
    assert(vmi);
    EXPECT_EQ(vmi->vhostsocket_filename(), "");
    EXPECT_EQ(vmi->vhostsocket_dir(), "" );
    /* GetVmVnPort is called from CNI via REST API */
    pih_->GetVmVnPort("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001", info);
    //cout << "GetPortInfo for vmi1 O/P" << ":" <<  info << "\n";
    client->WaitForIdle(10);

    assert(info.find("vhostnet1-000000000001"));

    pih_->DeleteVmVnPort(StringToUuid("00000000-0000-0000-0000-000000000001"),
            err_str);
    client->WaitForIdle(2);
}

/* Add/delete a port */
TEST_F(PortIpcTest, VmVn_Port_Add_Del_NoFilename) {

    std::string err_str;
    std::string cfgport_info;
    std::string info;

    /*  GetVmVnCfgPort is called from CNI via REST API  */
    pih_->GetVmVnCfgPort("vm1",cfgport_info);

    /*  AddVmVnPort is called from CNI Port Add via REST API
     *  GetVmVnCfgPort returns id, vm-uuid and vn-id as
     *  00000000-0000-0000-0000-000000000001 for this test case */
    AddVmVnPort("00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000001",
            "net1",
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000000",
            "vm1", "vhostnet1-000000000002",
            1,
            "/var/run/vrouter/d2aeb007-e09f-4051-962d-4587a75e6265", "");

    client->WaitForIdle(30);
    InterfaceConstRef vmi_ref =
        agent_->interface_table()->FindVmi(StringToUuid("00000000-0000-0000-0000-000000000001"));
    const VmInterface *vmi = dynamic_cast<const VmInterface *>(vmi_ref.get());
    assert(vmi);
    EXPECT_EQ(vmi->vhostsocket_filename(), "");
    EXPECT_EQ(vmi->vhostsocket_dir(), "/var/run/vrouter/d2aeb007-e09f-4051-962d-4587a75e6265" );
    /* GetVmVnPort is called from CNI via REST API */
    pih_->GetVmVnPort("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001", info);
    //cout << "GetPortInfo for vmi1 O/P" << ":" <<  info << "\n";
    client->WaitForIdle(10);

    assert(info.find("vhostnet1-000000000002"));

    pih_->DeleteVmVnPort(StringToUuid("00000000-0000-0000-0000-000000000001"),
            err_str);
    client->WaitForIdle(2);
}

int main (int argc, char **argv) {
    GETUSERARGS();
    client = TestInit(init_file, ksync_init);
    int ret = RUN_ALL_TESTS();
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
