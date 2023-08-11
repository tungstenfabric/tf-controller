/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#include "bgp/extended-community/local_sequence_number.h"

#include <stdio.h>

#include <algorithm>
#include <string>


using std::copy;
using std::string;

LocalSequenceNumber::LocalSequenceNumber(uint32_t seq) {
    data_[0] = BgpExtendedCommunityType::ExperimentalNonTransitive;
    data_[1] = BgpExtendedCommunityExperimentalNonTransitiveSubType::LocalSequenceNumber;
    put_value(&data_[2], 4, seq);
}

LocalSequenceNumber::LocalSequenceNumber(const bytes_type &data) {
    copy(data.begin(), data.end(), data_.begin());
}

uint32_t LocalSequenceNumber::local_sequence_number() const {
    uint8_t data[LocalSequenceNumber::kSize];
    copy(data_.begin(), data_.end(), &data[0]);
    if (data[0] == BgpExtendedCommunityType::ExperimentalNonTransitive &&
        data[1] == BgpExtendedCommunityExperimentalNonTransitiveSubType::LocalSequenceNumber) {
        uint32_t num = get_value(data + 2, 4);
        return num;
    }
    return 0;
}

std::string LocalSequenceNumber::ToString() {
    char temp[50];
    snprintf(temp, sizeof(temp), "local_sequence_number:%u",
        local_sequence_number());
    return string(temp);
}
