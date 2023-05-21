#include <cmn/agent_cmn.h>
#include <oper/interface_common.h>
#include "services/metadata_proxy.h"
#include "services/services_init.h"

void MetadataProxy::NetlinkAddVhostIp(const IpAddress& vhost_ll_ip) {
    LOG(ERROR, "MetadataProxy::NetlinkAddVhostIp is not implemented for "
    "FreeBSD, metadata_ipv6_netlink.cc, ");
    //assert(0);
}

void MetadataProxy::NetlinkDelVhostIp(const IpAddress& vhost_ll_ip) {
    LOG(ERROR, "MetadataProxy::NetlinkDelVhostIp is not implemented for "
    "FreeBSD, metadata_ipv6_netlink.cc, ");
    //assert(0);
}

void MetadataProxy::NetlinkAddVhostNb(const IpAddress& nb_ip,
    const MacAddress& via_mac) {
    LOG(ERROR, "MetadataProxy::NetlinkAddVhostNb is not implemented for "
    "FreeBSD, metadata_ipv6_netlink.cc, ");
    //assert(0);
}

//
//END-OF-FILE
//

