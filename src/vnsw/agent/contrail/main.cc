/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#include <boost/program_options.hpp>
#include <base/logging.h>
#include <base/contrail_ports.h>

#include <pugixml/pugixml.hpp>

#include <base/task.h>
#include <io/event_manager.h>
#include <sandesh/common/vns_types.h>
#include <sandesh/common/vns_constants.h>
#include <base/misc_utils.h>

#include <cmn/buildinfo.h>
#include <cmn/agent_cmn.h>

#include <cfg/cfg_init.h>
#include <cfg/cfg_mirror.h>

#include <init/agent_param.h>

#include <oper/operdb_init.h>
#include <oper/vrf.h>
#include <oper/multicast.h>
#include <oper/mirror_table.h>
#include <controller/controller_init.h>
#include <controller/controller_vrf_export.h>
#include <pkt/pkt_init.h>
#include <services/services_init.h>
#include <vrouter/ksync/ksync_init.h>
#include <uve/agent_uve.h>
#include <kstate/kstate.h>
#include <pkt/proto.h>
#include <diag/diag.h>
#include <boost/functional/factory.hpp>
#include <cmn/agent_factory.h>

#include "contrail_agent_init.h"
#define MAX_RETRY 60
namespace opt = boost::program_options;

void RouterIdDepInit(Agent *agent) {
    // Parse config and then connect
    Agent::GetInstance()->controller()->Connect();
    LOG(DEBUG, "Router ID Dependent modules (Nova and BGP) INITIALIZED");
}

bool is_vhost_interface_up() {
    struct ifreq ifr;
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    memset(&ifr, 0, sizeof(ifr));
    strcpy(ifr.ifr_name, "vhost0");
    int err = ioctl(sock, SIOCGIFFLAGS, &ifr);
    if (err < 0 || !(ifr.ifr_flags & IFF_UP)) {
        close(sock);
        LOG(DEBUG, "vhost is down");
        return false;
    }
    err = ioctl(sock, SIOCGIFADDR, &ifr);
    if (err < 0) {
        close(sock);
        LOG(DEBUG, "vhost is up, but ip is not set");
        return false;
    }
    close(sock);
    return true;
}

bool GetBuildInfo(std::string &build_info_str) {
    return MiscUtils::GetBuildInfo(MiscUtils::Agent, BuildInfo, build_info_str);
}

int main(int argc, char *argv[]) {
    AgentParam params;
    srand(unsigned(time(NULL)));
    try {
        params.ParseArguments(argc, argv);
    } catch (...) {
        std::cout << "Invalid arguments. ";
        std::cout << params.options() << std::endl;
        exit(0);
    }

    opt::variables_map var_map = params.var_map();
    if (var_map.count("help")) {
        std::cout << params.options() << std::endl;
        exit(0);
    }

    if (var_map.count("version")) {
        string build_info;
        MiscUtils::GetBuildInfo(MiscUtils::Agent, BuildInfo, build_info);
        std::cout << params.options() << std::endl;
        exit(0);
    }

    string init_file = "";
    if (var_map.count("config_file")) {
        init_file = var_map["config_file"].as<string>();
        struct stat s;
        if (stat(init_file.c_str(), &s) != 0) {
            std::cout << "Error opening config file <" << init_file
                 << ">. Error number <" << errno << ">";
            exit(EINVAL);
        }
    }

    // Read agent parameters from config file and arguments
    params.Init(init_file, argv[0]);

    if (!params.cat_is_agent_mocked() &&
         params.loopback_ip() == Ip4Address(0)) {

        uint16_t i;

        for (i = 0; i < MAX_RETRY; i++) {
            std::cout << "INFO: wait vhost0 to be initilaized... "
                << i << "/" << MAX_RETRY << std::endl;
            if (is_vhost_interface_up()) {
                std::cout << "INFO: vhost0 is ready." << std::endl;
                break;
            }
            usleep(5000000); //sleep for 5 seconds
        }

        if (i == MAX_RETRY) {
            std::cout << "INFO: vhost0 is not ready." << std::endl;
            exit(0);
        }
    }

    // Initialize TBB
    // Call to GetScheduler::GetInstance() will also create Task Scheduler
    TaskScheduler::Initialize(params.tbb_thread_count());

    // Initialize the agent-init control class
    ContrailAgentInit init;
    if (params.cat_is_agent_mocked()) {
        init.set_create_vhost(false);
    }

    init.set_agent_param(&params);
    // kick start initialization
    int ret = 0;
    if ((ret = init.Start()) != 0) {
        return ret;
    }

    string build_info;
    GetBuildInfo(build_info);
    MiscUtils::LogVersionInfo(build_info, Category::VROUTER);

    Agent *agent = init.agent();
    TaskScheduler::GetInstance()->set_event_manager(agent->event_manager());
    agent->event_manager()->Run();

    return 0;
}
