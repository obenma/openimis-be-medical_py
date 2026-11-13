"""
Feature tests for features/pricing-tariffs.feature (backend scenarios, module medical).
"""
import datetime
import json
import unittest

from django.core.cache import cache

from claim.models import ClaimService
from claim.test_helpers import create_test_claim
from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase
from core.test_helpers import create_security_tree, create_right_only_user, get_test_token, perm_ids
from insuree.test_helpers import create_test_insuree
from medical.apps import MedicalConfig
from medical.models import Diagnosis, Service
from medical.test_helpers import create_test_service, create_test_diagnosis
from program.test_helpers import create_test_program


class PricingTariffsFeatureTests(openIMISGraphQLTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = create_security_tree("FPT")
        cls.program = create_test_program(code="FPTP", name="FPT program")
        cls.user = create_right_only_user(
            "fptuser", sorted(set(perm_ids(MedicalConfig.gql_query_medical_services_perms))))

    def setUp(self):
        cache.clear()

    # Scenario: Claims entered before a tariff change keep the old price (@redmine-36640)
    def test_claims_entered_before_tariff_change_keep_old_price(self):
        service = create_test_service("A", custom_props={
            "code": "FPT-TR-1", "price": 2000, "program": self.program})
        icd = Diagnosis.objects.filter(validity_to__isnull=True).first() \
            or create_test_diagnosis({"code": "FPTD"})
        insuree = create_test_insuree(custom_props={"current_village": self.t.v1, "health_facility": self.t.hf1},
                                      family_custom_props={"location": self.t.v1})
        claim = create_test_claim(custom_props={
            "code": "FPT-CL-1", "health_facility_id": self.t.hf1.id, "insuree_id": insuree.id,
            "icd_id": icd.id, "program": self.program})
        line = ClaimService.objects.create(
            claim=claim, service=service, qty_provided=1, price_asked=service.price, status=1,
            validity_from="2019-06-01", audit_user_id=-1)

        # new tariff: a new service version
        service.save_history()
        service.price = 2500
        service.save()

        line.refresh_from_db()
        self.assertEqual(line.price_asked, 2000)
        current = Service.objects.get(code="FPT-TR-1", validity_to__isnull=True)
        self.assertEqual(current.price, 2500)

    # Scenario: A deactivated tariff is no longer offered (@redmine-36766 @redmine-37331)
    def test_deactivated_tariff_not_offered(self):
        old = create_test_service("A", custom_props={"code": "FPT-OLD-1", "program": self.program})
        new = create_test_service("A", custom_props={"code": "FPT-NEW-1", "program": self.program})
        Service.objects.filter(id=old.id).update(validity_to=datetime.datetime(2026, 6, 28))

        for query_name in ("medicalServices", "medicalServicesStr"):
            content = json.loads(self.query(
                'query { %s(code_Istartswith: "FPT-") { edges { node { code } } } }' % query_name,
                headers={"HTTP_AUTHORIZATION": f"Bearer {get_test_token(self.user)}"}).content)
            self.assertIsNone(content.get("errors"), content.get("errors"))
            codes = {e["node"]["code"] for e in content["data"][query_name]["edges"]}
            self.assertNotIn(old.code, codes, query_name)
            self.assertIn(new.code, codes, query_name)

    # Scenario: Dedicated transport tariff entry (@redmine-35617)
    @unittest.skip("open: #35617")
    def test_dedicated_transport_tariff_entry(self):
        pass
