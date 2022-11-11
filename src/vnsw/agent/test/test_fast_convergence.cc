/*
 * Copyright (c) 2016 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"
#include <boost/assign/list_of.hpp>

#include <cfg/cfg_init.h>
#include <oper/operdb_init.h>
#include <oper/global_system_config.h>
#include <controller/controller_init.h>
#include <pkt/pkt_init.h>
#include <services/services_init.h>
#include <vrouter/ksync/ksync_init.h>
#include <cmn/agent_cmn.h>
#include <base/task.h>
#include <io/event_manager.h>
#include <base/util.h>
#include <ifmap/ifmap_agent_parser.h>
#include <ifmap/ifmap_agent_table.h>
#include <oper/vn.h>
#include <oper/vm.h>
#include <oper/interface_common.h>

#include "testing/gunit.h"
#include "test_cmn_util.h"
#include "vr_types.h"

using namespace std;
using namespace boost::assign;

class FastConvTest : public ::testing::Test {
public:
    FastConvTest() : agent_(Agent::GetInstance()) {
    }

    Agent *agent_;
};

// Configure timer to 10s, then update to 30s.
// Assert if value got updated.
TEST_F(FastConvTest, Test_1) {
    AddFastConvergenceParameters(true, 10);
    client->WaitForIdle();
    FastConvergenceParameters fc_params =
                agent_->oper_db()->global_system_config()->fc_params();
    EXPECT_TRUE(fc_params.enable);
    EXPECT_TRUE(fc_params.xmpp_hold_time == 10);
    EXPECT_TRUE(agent_->controller()->VerifyXmppServerTimeout(10));

    AddFastConvergenceParameters(true, 30);
    client->WaitForIdle();
    fc_params = agent_->oper_db()->global_system_config()->fc_params();
    EXPECT_TRUE(fc_params.enable);
    EXPECT_TRUE(fc_params.xmpp_hold_time == 30);
    EXPECT_TRUE(agent_->controller()->VerifyXmppServerTimeout(30));

    DelFastConvergenceParameters();
    client->WaitForIdle();
}

//  Disable fast convergence and then check if values are still updated.
//  Changes should not be seen.
TEST_F(FastConvTest, Test_2) {
    AddFastConvergenceParameters(true, 10);
    client->WaitForIdle();
    FastConvergenceParameters fc_params =
                agent_->oper_db()->global_system_config()->fc_params();
    EXPECT_TRUE(fc_params.enable);
    EXPECT_TRUE(agent_->controller()->VerifyXmppServerTimeout(10));

    AddFastConvergenceParameters(false, 30);
    client->WaitForIdle();
    fc_params = agent_->oper_db()->global_system_config()->fc_params();
    EXPECT_FALSE(fc_params.enable);
    EXPECT_FALSE(fc_params.xmpp_hold_time == 30);

    DelFastConvergenceParameters();
    client->WaitForIdle();
}

int main(int argc, char **argv) {
    GETUSERARGS();

    client = TestInit(init_file, ksync_init);
    int ret = RUN_ALL_TESTS();
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
