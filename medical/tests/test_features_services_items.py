"""
Feature tests for features/services-items.feature (backend scenarios).
Health-facility-specific services and items (transport tariffs).
"""
import json
import uuid

from django.core.cache import cache

from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase
from core.test_helpers import create_security_tree, create_right_only_user, get_test_token, perm_ids
from medical.apps import MedicalConfig
from medical.gql_mutations import CreateServiceMutation, CreateItemMutation
from medical.models import Item, Service
from medical.test_helpers import create_test_item, create_test_service
from program.test_helpers import create_test_program


class ServicesItemsFeatureTests(openIMISGraphQLTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = create_security_tree("FSI")
        cls.hf_a, cls.hf_b = cls.t.hf1, cls.t.hf2
        cls.program = create_test_program(code="FSIP", name="FSI program")
        cls.user = create_right_only_user(
            "fsiuser",
            sorted(set(perm_ids(
                MedicalConfig.gql_query_medical_services_perms
                + MedicalConfig.gql_query_medical_items_perms
                + MedicalConfig.gql_mutation_medical_services_add_perms
                + MedicalConfig.gql_mutation_medical_items_add_perms))))
        props = {"program": cls.program}
        cls.s_a = create_test_service("A", custom_props={**props, "code": "FSI-S-A", "health_facility": cls.hf_a})
        cls.s_b = create_test_service("A", custom_props={**props, "code": "FSI-S-B", "health_facility": cls.hf_b})
        cls.s_all = create_test_service("A", custom_props={**props, "code": "FSI-S-ALL"})
        cls.i_a = create_test_item("D", custom_props={**props, "code": "FSIIA", "health_facility": cls.hf_a})
        cls.i_b = create_test_item("D", custom_props={**props, "code": "FSIIB", "health_facility": cls.hf_b})
        cls.i_all = create_test_item("D", custom_props={**props, "code": "FSIIAL"})

    def setUp(self):
        cache.clear()

    def _gql(self, query):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {get_test_token(self.user)}"}
        return json.loads(self.query(query, headers=headers).content)

    def _create_data(self, code, **extra):
        return {
            "client_mutation_id": str(uuid.uuid4()),
            "code": code, "name": "FSI " + code, "type": "C", "care_type": "O",
            "patient_category": 15, "price": 1000, "program": self.program.idProgram,
            **extra,
        }

    # ------------------------------------------------------------------ create
    # Scenario: Service created without a health facility (@redmine-28704)
    def test_service_created_without_health_facility(self):
        errors = CreateServiceMutation.async_mutate(
            self.user, **self._create_data("FSI-NEW-S", level="H", packagetype="S"))
        self.assertFalse(errors, errors)
        service = Service.objects.get(code="FSI-NEW-S", validity_to__isnull=True)
        self.assertIsNone(service.health_facility_id)

    # Scenario: Item created without a health facility (@redmine-28704)
    def test_item_created_without_health_facility(self):
        errors = CreateItemMutation.async_mutate(
            self.user, **self._create_data("FSINI", package="box", quantity=1))
        self.assertFalse(errors, errors)
        item = Item.objects.get(code="FSINI", validity_to__isnull=True)
        self.assertIsNone(item.health_facility_id)

    # Scenario: Service created for a health facility (@redmine-28704)
    def test_service_created_for_health_facility(self):
        errors = CreateServiceMutation.async_mutate(
            self.user, **self._create_data("FSI-HF-S", level="H", packagetype="S",
                                           health_facility=self.hf_a.id))
        self.assertFalse(errors, errors)
        service = Service.objects.get(code="FSI-HF-S", validity_to__isnull=True)
        self.assertEqual(service.health_facility_id, self.hf_a.id)
        content = self._gql('query { medicalServices(code: "FSI-HF-S") '
                            '{ edges { node { code healthFacility { code } } } } }')
        self.assertIsNone(content.get("errors"), content.get("errors"))
        node = content["data"]["medicalServices"]["edges"][0]["node"]
        self.assertEqual(node["healthFacility"]["code"], self.hf_a.code)

    # Scenario: Unknown health facility is refused (@redmine-28704)
    def test_unknown_health_facility_refused(self):
        errors = CreateServiceMutation.async_mutate(
            self.user, **self._create_data("FSI-BAD-S", level="H", packagetype="S",
                                           health_facility=999999))
        self.assertTrue(errors)
        self.assertIn("La FOSA avec l'ID 999999 n'existe pas", errors[0]["detail"])
        self.assertFalse(Service.objects.filter(code="FSI-BAD-S").exists())

    # ------------------------------------------------------------------ claiming filter
    def _codes(self, query_name, node_prefix):
        content = self._gql('query { %s(healthFacilityId: %s, code_Istartswith: "%s") '
                            '{ edges { node { code } } } }' % (query_name, self.hf_a.id, node_prefix))
        self.assertIsNone(content.get("errors"), content.get("errors"))
        return {e["node"]["code"] for e in content["data"][query_name]["edges"]}

    # Scenario: Services and items offered when claiming for a health facility (medicalServices) (@redmine-29304)
    def test_medical_services_filtered_by_hf(self):
        self.assertEqual(self._codes("medicalServices", "FSI-S-"), {"FSI-S-A", "FSI-S-ALL"})

    # Scenario: Services and items offered when claiming for a health facility (medicalServicesStr) (@redmine-29304)
    def test_medical_services_str_filtered_by_hf(self):
        self.assertEqual(self._codes("medicalServicesStr", "FSI-S-"), {"FSI-S-A", "FSI-S-ALL"})

    # Scenario: Services and items offered when claiming for a health facility (medicalItems) (@redmine-29304)
    def test_medical_items_filtered_by_hf(self):
        self.assertEqual(self._codes("medicalItems", "FSII"), {"FSIIA", "FSIIAL"})

    # Scenario: Services and items offered when claiming for a health facility (medicalItemsStr) (@redmine-29304)
    def test_medical_items_str_filtered_by_hf(self):
        self.assertEqual(self._codes("medicalItemsStr", "FSII"), {"FSIIA", "FSIIAL"})
