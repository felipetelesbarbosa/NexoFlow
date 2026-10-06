import unittest

from contact_enrichment import infer_contact_fields


class ContactEnrichmentTests(unittest.TestCase):
    def test_explicit_age_updates_age_and_majority(self) -> None:
        messages = [
            {
                "id": 1,
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "Tenho 27 anos",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"1"})
        self.assertEqual(result["idade"].value, 27)
        self.assertEqual(result["maior_de_18_anos"].value, "sim")

    def test_minor_age_updates_majority_no(self) -> None:
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "Eu tenho 16 anos.",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"m1"})
        self.assertEqual(result["idade"].value, 16)
        self.assertEqual(result["maior_de_18_anos"].value, "não")

    def test_standalone_age_requires_context(self) -> None:
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Qual a sua idade?",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "34",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertEqual(result["idade"].value, 34)
        self.assertEqual(result["maior_de_18_anos"].value, "sim")

    def test_standalone_number_without_context_is_ignored(self) -> None:
        messages = [
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "34",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertNotIn("idade", result)

    def test_yes_after_majority_question(self) -> None:
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Você é maior de 18 anos?",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "Sim",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertEqual(result["maior_de_18_anos"].value, "sim")
        self.assertNotIn("idade", result)

    def test_yes_after_lgpd_context_activates_optin(self) -> None:
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Você autoriza o tratamento dos seus dados pessoais conforme a LGPD?",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "Sim",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertEqual(result["opt_in_lgpd"].value, "ativo")

    def test_no_after_lgpd_context_sets_refused(self) -> None:
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Consentimento LGPD para tratamento de dados pessoais. Aceita?",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "Não",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertEqual(result["opt_in_lgpd"].value, "recusado")

    def test_unrelated_yes_does_not_change_lgpd(self) -> None:
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Você quer receber o pedido hoje?",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "Sim",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertNotIn("opt_in_lgpd", result)
        self.assertNotIn("maior_de_18_anos", result)

    def test_explicit_formatted_cpf_is_normalized(self) -> None:
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "Meu CPF é 529.982.247-25",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"m1"})
        self.assertEqual(result["cpf"].value, "52998224725")

    def test_standalone_cpf_requires_cpf_context(self) -> None:
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Por favor, informe seu CPF.",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "52998224725",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertEqual(result["cpf"].value, "52998224725")

    def test_standalone_cpf_without_context_is_ignored(self) -> None:
        messages = [
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:05Z",
                "direction": "in",
                "text": "52998224725",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"a1"})
        self.assertNotIn("cpf", result)

    def test_invalid_cpf_is_ignored(self) -> None:
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "Meu CPF é 111.111.111-11",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"m1"})
        self.assertNotIn("cpf", result)

    def test_most_recent_valid_cpf_wins(self) -> None:
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "Meu CPF é 529.982.247-25",
            },
            {
                "id": "m2",
                "created_on": "2026-10-03T12:10:00Z",
                "direction": "in",
                "text": "Correção: meu CPF é 168.995.350-09",
            },
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"m1", "m2"})
        self.assertEqual(result["cpf"].value, "16899535009")
        self.assertEqual(result["cpf"].message_id, "m2")

    def test_cpf_of_third_party_is_not_used_as_contact_cpf(self) -> None:
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "O CPF da minha mãe é 529.982.247-25",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"m1"})
        self.assertNotIn("cpf", result)

    def test_message_with_multiple_valid_cpfs_is_ignored_as_ambiguous(self) -> None:
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "CPF 52998224725 ou CPF 16899535009",
            }
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"m1"})
        self.assertNotIn("cpf", result)


if __name__ == "__main__":
    unittest.main()
