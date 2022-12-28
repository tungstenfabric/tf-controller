/*
 *  * Copyright (c) 2021 Juniper Networks, Inc. All rights reserved.
 *   */
#include <base/task.h>
#include <cmn/agent.h>

typedef void (*cxa_throw_type)(void *, void *, void (*) (void *));
cxa_throw_type AgentCxaThrow = 0;

void LoadAgentThrow()
{
    AgentCxaThrow = (cxa_throw_type)dlsym(RTLD_NEXT, "__cxa_throw");
}

void __cxa_throw (void *thrown_exception, void *pvtinfo, void (*dest)(void *))
{

    if (AgentCxaThrow == 0)
        LoadAgentThrow();

    assert(0);

    AgentCxaThrow(thrown_exception, pvtinfo, dest);
    while(1);
}
