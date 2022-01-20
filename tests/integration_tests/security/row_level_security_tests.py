# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# isort:skip_file
import re
from typing import Any, Dict, List
from unittest import mock

import pytest
from flask import g

from superset import db, security_manager
from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable
from superset.security.guest_token import GuestTokenRlsRule, GuestTokenResourceType
from ..base_tests import SupersetTestCase
from tests.integration_tests.fixtures.birth_names_dashboard import (
    load_birth_names_dashboard_with_slices,
    load_birth_names_data,
)
from tests.integration_tests.fixtures.energy_dashboard import (
    load_energy_table_with_slice,
    load_energy_table_data,
)
from tests.integration_tests.fixtures.unicode_dashboard import (
    load_unicode_dashboard_with_slice,
    load_unicode_data,
)


query_obj: Dict[str, Any] = dict(
    groupby=[],
    metrics=None,
    filter=[],
    is_timeseries=False,
    columns=["value"],
    granularity=None,
    from_dttm=None,
    to_dttm=None,
    extras={},
)
NAME_AB_ROLE = "NameAB"
NAME_Q_ROLE = "NameQ"
NAMES_A_REGEX = re.compile(r"name like 'A%'")
NAMES_B_REGEX = re.compile(r"name like 'B%'")
NAMES_Q_REGEX = re.compile(r"name like 'Q%'")
BASE_FILTER_REGEX = re.compile(r"gender = 'boy'")


class TestRowLevelSecurity(SupersetTestCase):
    """
    Testing Row Level Security
    """

    def setUp(self):
        session = db.session

        # Create roles
        security_manager.add_role(NAME_AB_ROLE)
        security_manager.add_role(NAME_Q_ROLE)
        gamma_user = security_manager.find_user(username="gamma")
        gamma_user.roles.append(security_manager.find_role(NAME_AB_ROLE))
        gamma_user.roles.append(security_manager.find_role(NAME_Q_ROLE))
        self.create_user_with_roles("NoRlsRoleUser", ["Gamma"])
        session.commit()

        # Create regular RowLevelSecurityFilter (energy_usage, unicode_test)
        self.rls_entry1 = RowLevelSecurityFilter()
        self.rls_entry1.tables.extend(
            session.query(SqlaTable)
            .filter(SqlaTable.table_name.in_(["energy_usage", "unicode_test"]))
            .all()
        )
        self.rls_entry1.filter_type = "Regular"
        self.rls_entry1.clause = "value > {{ cache_key_wrapper(1) }}"
        self.rls_entry1.group_key = None
        self.rls_entry1.roles.append(security_manager.find_role("Gamma"))
        self.rls_entry1.roles.append(security_manager.find_role("Alpha"))
        db.session.add(self.rls_entry1)

        # Create regular RowLevelSecurityFilter (birth_names name starts with A or B)
        self.rls_entry2 = RowLevelSecurityFilter()
        self.rls_entry2.tables.extend(
            session.query(SqlaTable)
            .filter(SqlaTable.table_name.in_(["birth_names"]))
            .all()
        )
        self.rls_entry2.filter_type = "Regular"
        self.rls_entry2.clause = "name like 'A%' or name like 'B%'"
        self.rls_entry2.group_key = "name"
        self.rls_entry2.roles.append(security_manager.find_role("NameAB"))
        db.session.add(self.rls_entry2)

        # Create Regular RowLevelSecurityFilter (birth_names name starts with Q)
        self.rls_entry3 = RowLevelSecurityFilter()
        self.rls_entry3.tables.extend(
            session.query(SqlaTable)
            .filter(SqlaTable.table_name.in_(["birth_names"]))
            .all()
        )
        self.rls_entry3.filter_type = "Regular"
        self.rls_entry3.clause = "name like 'Q%'"
        self.rls_entry3.group_key = "name"
        self.rls_entry3.roles.append(security_manager.find_role("NameQ"))
        db.session.add(self.rls_entry3)

        # Create Base RowLevelSecurityFilter (birth_names boys)
        self.rls_entry4 = RowLevelSecurityFilter()
        self.rls_entry4.tables.extend(
            session.query(SqlaTable)
            .filter(SqlaTable.table_name.in_(["birth_names"]))
            .all()
        )
        self.rls_entry4.filter_type = "Base"
        self.rls_entry4.clause = "gender = 'boy'"
        self.rls_entry4.group_key = "gender"
        self.rls_entry4.roles.append(security_manager.find_role("Admin"))
        db.session.add(self.rls_entry4)

        db.session.commit()

    def tearDown(self):
        session = db.session
        session.delete(self.rls_entry1)
        session.delete(self.rls_entry2)
        session.delete(self.rls_entry3)
        session.delete(self.rls_entry4)
        session.delete(security_manager.find_role("NameAB"))
        session.delete(security_manager.find_role("NameQ"))
        session.delete(self.get_user("NoRlsRoleUser"))
        session.commit()

    @pytest.mark.usefixtures("load_energy_table_with_slice")
    def test_rls_filter_alters_energy_query(self):
        g.user = self.get_user(username="alpha")
        tbl = self.get_table(name="energy_usage")
        sql = tbl.get_query_str(query_obj)
        assert tbl.get_extra_cache_keys(query_obj) == [1]
        assert "value > 1" in sql

    @pytest.mark.usefixtures("load_energy_table_with_slice")
    def test_rls_filter_doesnt_alter_energy_query(self):
        g.user = self.get_user(
            username="admin"
        )  # self.login() doesn't actually set the user
        tbl = self.get_table(name="energy_usage")
        sql = tbl.get_query_str(query_obj)
        assert tbl.get_extra_cache_keys(query_obj) == []
        assert "value > 1" not in sql

    @pytest.mark.usefixtures("load_unicode_dashboard_with_slice")
    def test_multiple_table_filter_alters_another_tables_query(self):
        g.user = self.get_user(
            username="alpha"
        )  # self.login() doesn't actually set the user
        tbl = self.get_table(name="unicode_test")
        sql = tbl.get_query_str(query_obj)
        assert tbl.get_extra_cache_keys(query_obj) == [1]
        assert "value > 1" in sql

    @pytest.mark.usefixtures("load_birth_names_dashboard_with_slices")
    def test_rls_filter_alters_gamma_birth_names_query(self):
        g.user = self.get_user(username="gamma")
        tbl = self.get_table(name="birth_names")
        sql = tbl.get_query_str(query_obj)

        # establish that the filters are grouped together correctly with
        # ANDs, ORs and parens in the correct place
        assert (
            "WHERE ((name like 'A%'\n        or name like 'B%')\n       OR (name like 'Q%'))\n  AND (gender = 'boy');"
            in sql
        )

    @pytest.mark.usefixtures("load_birth_names_dashboard_with_slices")
    def test_rls_filter_alters_no_role_user_birth_names_query(self):
        g.user = self.get_user(username="NoRlsRoleUser")
        tbl = self.get_table(name="birth_names")
        sql = tbl.get_query_str(query_obj)

        # gamma's filters should not be present query
        assert not NAMES_A_REGEX.search(sql)
        assert not NAMES_B_REGEX.search(sql)
        assert not NAMES_Q_REGEX.search(sql)
        # base query should be present
        assert BASE_FILTER_REGEX.search(sql)

    @pytest.mark.usefixtures("load_birth_names_dashboard_with_slices")
    def test_rls_filter_doesnt_alter_admin_birth_names_query(self):
        g.user = self.get_user(username="admin")
        tbl = self.get_table(name="birth_names")
        sql = tbl.get_query_str(query_obj)

        # no filters are applied for admin user
        assert not NAMES_A_REGEX.search(sql)
        assert not NAMES_B_REGEX.search(sql)
        assert not NAMES_Q_REGEX.search(sql)
        assert not BASE_FILTER_REGEX.search(sql)


RLS_ALICE_REGEX = re.compile(r"name = 'Alice'")
RLS_GENDER_REGEX = re.compile(r"gender = 'girl'")


@mock.patch.dict(
    "superset.extensions.feature_flag_manager._feature_flags", EMBEDDED_SUPERSET=True,
)
class GuestTokenRowLevelSecurityTests(SupersetTestCase):
    def default_rls_rule(self):
        return {
            "dataset": self.get_table(name="birth_names").id,
            "clause": "name = 'Alice'",
        }

    def guest_user_with_rls(self, rules: List[Any] = None):
        if rules is None:
            rules = [self.default_rls_rule()]
        return security_manager.get_guest_user_from_token(
            {
                "user": {},
                "resources": [{"type": GuestTokenResourceType.DASHBOARD.value}],
                "rls_rules": rules,
            }
        )

    @pytest.mark.usefixtures("load_birth_names_dashboard_with_slices")
    def test_rls_filter_alters_query(self):
        g.user = self.guest_user_with_rls()
        tbl = self.get_table(name="birth_names")
        sql = tbl.get_query_str(query_obj)

        self.assertRegexpMatches(sql, RLS_ALICE_REGEX)

    @pytest.mark.usefixtures("load_birth_names_dashboard_with_slices")
    def test_rls_filter_does_not_alter_unrelated_query(self):
        g.user = self.guest_user_with_rls(
            rules=[
                {
                    "dataset": self.get_table(name="birth_names").id + 1,
                    "clause": "name = 'Alice'",
                }
            ]
        )
        tbl = self.get_table(name="birth_names")
        sql = tbl.get_query_str(query_obj)

        self.assertNotRegexpMatches(sql, RLS_ALICE_REGEX)

    @pytest.mark.usefixtures("load_birth_names_dashboard_with_slices")
    def test_multiple_rls_filters_are_unionized(self):
        g.user = self.guest_user_with_rls(
            rules=[
                self.default_rls_rule(),
                {
                    "dataset": self.get_table(name="birth_names").id,
                    "clause": "gender = 'girl'",
                },
            ]
        )
        tbl = self.get_table(name="birth_names")
        sql = tbl.get_query_str(query_obj)

        self.assertRegexpMatches(sql, RLS_ALICE_REGEX)
        self.assertRegexpMatches(sql, RLS_GENDER_REGEX)
