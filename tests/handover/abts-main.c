/*
 * Copyright (C) 2019 by Sukchan Lee <acetcom@gmail.com>
 *
 * This file is part of Open5GS.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

#include "test-app.h"

abts_suite *test_epc_x2(abts_suite *suite);
abts_suite *test_epc_s1(abts_suite *suite);
abts_suite *test_5gc_xn(abts_suite *suite);
abts_suite *test_5gc_n2(abts_suite *suite);

const struct testlist {
    abts_suite *(*func)(abts_suite *suite);
    const char *name;
} alltests[] = {
    {test_epc_x2, "epc-x2"},
    {test_epc_s1, "epc-s1"},
    {test_5gc_xn, "5gc-xn"},
    {test_5gc_n2, "5gc-n2"},
    {NULL, NULL},
};

/* Branch-only diagnostics; do not change production NF behaviour. */
static bool diagnostics_enabled = false;

static void checkpoint(const char *phase)
{
    if (diagnostics_enabled)
        fprintf(stderr, "[HO-DIAG] %s\n", phase);
}

static void terminate(void)
{
    ogs_msleep(50);

    checkpoint("terminate: test_child_terminate BEGIN");
    test_child_terminate();
    checkpoint("terminate: test_child_terminate END; app_terminate BEGIN");
    app_terminate();
    checkpoint("terminate: app_terminate END; test_app_final BEGIN");
    test_app_final();
    checkpoint("terminate: test_app_final END; ogs_app_terminate BEGIN");
    ogs_app_terminate();
    checkpoint("terminate: ogs_app_terminate END");
}

static void initialize(const char *const argv[])
{
    int rv;

    rv = ogs_app_initialize(NULL, NULL, argv);
    ogs_assert(rv == OGS_OK);
    test_app_init();

    rv = app_initialize(argv);
    ogs_assert(rv == OGS_OK);
}

int main(int argc, const char *const argv[])
{
    int i;
    const char *diagnostics = getenv("OGS_HO_DIAGNOSTICS");
    abts_suite *suite = NULL;

    diagnostics_enabled = diagnostics && !strcmp(diagnostics, "1");
    if (diagnostics_enabled) {
        /* Child NF output is relayed through this process's stdout. */
        setvbuf(stdout, NULL, _IONBF, 0);
        setvbuf(stderr, NULL, _IONBF, 0);
    }

    atexit(terminate);
    checkpoint("initialize BEGIN");
    test_app_run(argc, argv, "sample.yaml", initialize);
    checkpoint("initialize END");

    for (i = 0; alltests[i].func; i++) {
        if (diagnostics_enabled)
            fprintf(stderr, "[HO-DIAG] suite %s BEGIN\n", alltests[i].name);
        suite = alltests[i].func(suite);
        if (diagnostics_enabled)
            fprintf(stderr, "[HO-DIAG] suite %s END\n", alltests[i].name);
    }

    checkpoint("abts_report BEGIN");

    return abts_report(suite);
}
