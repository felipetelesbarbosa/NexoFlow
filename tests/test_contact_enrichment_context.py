import unittest
from datetime import UTC, datetime, timedelta

from config import WENI_UPDATE_CONTEXT_LOOKBACK_HOURS
from contact_enrichment import infer_contact_fields


class ContactEnrichmentContextTests(unittest.TestCase):
    prompt = "Você autoriza o tratamento dos seus dados pessoais conforme a LGPD?"
    start = datetime(2026, 10, 3, 12, tzinfo=UTC)
    combined_prompt = (
        "Para prosseguirmos com seu atendimento, confirme se você tem mais de 18 anos "
        "e autoriza o uso dos seus dados para realizarmos a entrega. "
        "Essa autorização será registrada apenas uma vez. Responda “SIM” para continuar!"
    )

    def message(self, number, text, *, direction="in", after=None):
        return {
            "id": str(number),
            "created_on": (
                self.start + (after or timedelta(seconds=number))
            ).isoformat(),
            "direction": direction,
            "text": text,
        }

    def infer_reply(self, reply, *, prompt=None, current_lgpd=None):
        messages = [
            self.message(1, prompt or self.prompt, direction="out"),
            self.message(2, reply),
        ]
        return infer_contact_fields(
            messages, candidate_message_ids={"2"}, current_lgpd=current_lgpd
        )

    def test_compound_explicit_acceptance_is_recorded(self):
        for reply in (
            "Sim, pode continuar",
            "Aceito, vamos seguir",
            "Autorizo!",
            "Eu aceito",
        ):
            with self.subTest(reply=reply):
                result = self.infer_reply(reply)
                self.assertEqual(result["opt_in_lgpd"].value, "ativo")
                self.assertEqual(result["opt_in_lgpd"].message_id, "2")
                self.assertIn("pergunta LGPD 1", result["opt_in_lgpd"].reason)
                self.assertNotIn("marketing_opt_in", result)

    def test_compound_refusal_takes_precedence_over_acceptance(self):
        for reply in (
            "Não, não quero que usem meus dados",
            "Não autorizo, mas quero fazer o pedido",
            "Sim, quero atendimento, mas não aceito o tratamento dos dados",
            "Não autorizo o tratamento dos dados pessoais, talvez mais tarde",
            "Não, não quero usar meus dados pessoais, mas aceito falar com atendente",
        ):
            with self.subTest(reply=reply):
                result = self.infer_reply(reply)
                self.assertEqual(result["opt_in_lgpd"].value, "recusado")

    def test_uncertain_reply_is_not_a_decision(self):
        for reply in (
            "Não sei",
            "Não entendi",
            "Talvez",
            "Aceito se não guardarem meus dados",
            "Não sei se aceito a LGPD",
        ):
            with self.subTest(reply=reply):
                self.assertNotIn("opt_in_lgpd", self.infer_reply(reply))

    def test_continuation_is_only_operational_consent(self):
        for reply in (
            "Pode prosseguir",
            "Quero continuar o atendimento",
            "Quero fazer meu pedido",
        ):
            with self.subTest(reply=reply):
                result = self.infer_reply(reply)
                self.assertEqual(result["opt_in_lgpd"].value, "ativo")
                self.assertIn("continuidade explícita", result["opt_in_lgpd"].reason)
                self.assertIn(
                    "sem consentimento de marketing", result["opt_in_lgpd"].reason
                )
                self.assertNotIn("marketing_opt_in", result)

    def test_continuation_does_not_replace_existing_refusal(self):
        for refusal in ("recusado", "Não", "negado"):
            with self.subTest(refusal=refusal):
                self.assertNotIn(
                    "opt_in_lgpd",
                    self.infer_reply("Pode continuar", current_lgpd=refusal),
                )

    def test_refusal_in_context_survives_later_continuation(self):
        messages = [
            self.message(1, self.prompt, direction="out"),
            self.message(2, "Não, não autorizo"),
            self.message(3, self.prompt, direction="out"),
            self.message(4, "Pode continuar"),
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"2", "4"})
        self.assertEqual(result["opt_in_lgpd"].value, "recusado")
        self.assertEqual(result["opt_in_lgpd"].message_id, "2")
        result = infer_contact_fields(messages, candidate_message_ids={"4"})
        self.assertNotIn("opt_in_lgpd", result)

    def test_explicit_later_acceptance_can_replace_refusal(self):
        result = self.infer_reply("Sim, autorizo", current_lgpd="recusado")
        self.assertEqual(result["opt_in_lgpd"].value, "ativo")

    def test_later_sim_to_explicit_consent_instruction_replaces_earlier_refusal(self):
        messages = [
            self.message(1, self.prompt, direction="out"),
            self.message(2, "Não"),
            self.message(
                3,
                "O consentimento é necessário para o atendimento. "
                "Se quiser continuar, me responda com *sim* aos termos de atendimento e uso de dados.",
                direction="out",
            ),
            self.message(4, "Sim"),
        ]
        result = infer_contact_fields(
            messages, candidate_message_ids={"2", "4"}, current_lgpd="recusado"
        )
        self.assertEqual(result["opt_in_lgpd"].value, "ativo")
        self.assertEqual(result["opt_in_lgpd"].message_id, "4")
        self.assertNotIn("marketing_opt_in", result)

    def test_information_instruction_is_not_consent_authorization(self):
        result = self.infer_reply(
            "Sim", prompt="Responda SIM para ler mais informações sobre LGPD."
        )
        self.assertNotIn("opt_in_lgpd", result)

    def test_direct_explicit_acceptance_survives_intermediate_question(self):
        messages = [
            self.message(1, self.prompt, direction="out"),
            self.message(2, "Informe seu CPF", direction="out"),
            self.message(3, "Concordo com o tratamento dos dados conforme a LGPD"),
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"3"})
        self.assertEqual(result["opt_in_lgpd"].value, "ativo")

    def test_unrelated_reply_after_intermediate_question_is_not_consent(self):
        messages = [
            self.message(1, self.prompt, direction="out"),
            self.message(2, "Você quer receber o pedido hoje?", direction="out"),
            self.message(3, "Sim, pode continuar"),
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"3"})
        self.assertNotIn("opt_in_lgpd", result)

    def test_outgoing_text_cannot_declare_customer_consent_or_refusal(self):
        for text in (
            "Eu aceito a LGPD",
            "Não autorizo o tratamento dos dados pessoais",
        ):
            with self.subTest(text=text):
                message = self.message(1, text, direction="out")
                result = infer_contact_fields([message], candidate_message_ids={"1"})
                self.assertNotIn("opt_in_lgpd", result)

    def test_unknown_direction_does_not_declare_consent(self):
        message = self.message(1, "Eu aceito a LGPD", direction="")
        self.assertNotIn(
            "opt_in_lgpd", infer_contact_fields([message], candidate_message_ids={"1"})
        )

    def test_incoming_folder_can_supply_direction(self):
        message = self.message(1, "Eu aceito a LGPD", direction="")
        message["folder"] = "incoming"
        result = infer_contact_fields([message], candidate_message_ids={"1"})
        self.assertEqual(result["opt_in_lgpd"].value, "ativo")

    def test_context_uses_existing_session_window(self):
        for offset, available in (
            (timedelta(hours=WENI_UPDATE_CONTEXT_LOOKBACK_HOURS), True),
            (timedelta(hours=WENI_UPDATE_CONTEXT_LOOKBACK_HOURS, seconds=1), False),
        ):
            with self.subTest(offset=offset):
                messages = [
                    self.message(0, self.prompt, direction="out"),
                    self.message(1, "Sim", after=offset),
                ]
                result = infer_contact_fields(messages, candidate_message_ids={"1"})
                self.assertEqual("opt_in_lgpd" in result, available)

    def test_invalid_or_missing_timestamps_do_not_link_consent(self):
        for value in ("", "data inválida"):
            for position in (0, 1):
                with self.subTest(value=value, position=position):
                    messages = [
                        self.message(1, self.prompt, direction="out"),
                        self.message(2, "Sim"),
                    ]
                    messages[position]["created_on"] = value
                    result = infer_contact_fields(messages, candidate_message_ids={"2"})
                    self.assertNotIn("opt_in_lgpd", result)

    def test_direct_consent_also_requires_valid_timestamp(self):
        message = self.message(1, "Eu aceito a LGPD")
        message["created_on"] = ""
        result = infer_contact_fields([message], candidate_message_ids={"1"})
        self.assertNotIn("opt_in_lgpd", result)

    def test_bundled_marketing_question_is_not_operational_consent(self):
        for reply in ("Sim", "Pode continuar"):
            with self.subTest(reply=reply):
                result = self.infer_reply(
                    reply,
                    prompt="Você aceita a LGPD e receber ofertas e promoções?",
                )
                self.assertNotIn("opt_in_lgpd", result)
                self.assertNotIn("marketing_opt_in", result)

    def test_multiple_questions_do_not_make_continuation_a_decision(self):
        for prompt in (
            "Você aceita a LGPD? Quer receber o pedido hoje?",
            "Você é maior de 18 anos e aceita a LGPD?",
            "Você aceita a LGPD e confirma seu CPF?",
        ):
            with self.subTest(prompt=prompt):
                self.assertNotIn(
                    "opt_in_lgpd", self.infer_reply("Pode continuar", prompt=prompt)
                )

    def test_order_confirmation_delivery_and_silence_do_not_grant_consent(self):
        for reply in ("Pedido feito", "Pedido em rota", "Saiu para entrega", ""):
            with self.subTest(reply=reply):
                result = self.infer_reply(reply)
                self.assertNotIn("opt_in_lgpd", result)
                self.assertNotIn("marketing_opt_in", result)

    def test_explicit_combined_prompt_sim_confirms_majority_and_operational_consent(
        self,
    ):
        for reply in (
            "SIM",
            "Sim, pode continuar",
            "Sim, sou maior de idade e autorizo",
        ):
            with self.subTest(reply=reply):
                result = self.infer_reply(reply, prompt=self.combined_prompt)
                self.assertEqual(result["maior_de_18_anos"].value, "sim")
                self.assertEqual(result["opt_in_lgpd"].value, "ativo")
                self.assertNotIn("idade", result)
                self.assertNotIn("marketing_opt_in", result)

    def test_combined_prompt_does_not_assign_both_negatives_to_bare_nao(self):
        result = self.infer_reply("Não", prompt=self.combined_prompt)
        self.assertNotIn("opt_in_lgpd", result)
        self.assertNotIn("maior_de_18_anos", result)

    def test_combined_prompt_preserves_separate_explicit_decisions(self):
        for reply, majority, consent in (
            ("Sou maior de 18 anos, não autorizo", "sim", "recusado"),
            ("Sou menor de idade e não autorizo", "não", "recusado"),
            ("Não, não autorizo", None, "recusado"),
            ("Não sou maior de idade", "não", None),
            (
                "Não sou maior de idade, mas autorizo o uso dos meus dados para entrega",
                "não",
                "ativo",
            ),
        ):
            with self.subTest(reply=reply):
                result = self.infer_reply(reply, prompt=self.combined_prompt)
                self.assertEqual(
                    result["maior_de_18_anos"].value
                    if "maior_de_18_anos" in result
                    else None,
                    majority,
                )
                self.assertEqual(
                    result["opt_in_lgpd"].value if "opt_in_lgpd" in result else None,
                    consent,
                )
                self.assertNotIn("marketing_opt_in", result)

    def test_combined_prompt_requires_sim_not_implicit_continuation(self):
        result = self.infer_reply("Pode continuar", prompt=self.combined_prompt)
        self.assertNotIn("opt_in_lgpd", result)
        self.assertNotIn("maior_de_18_anos", result)

    def test_combined_prompt_does_not_include_marketing_or_cpf(self):
        for addition in (
            " Você também autoriza ofertas de marketing.",
            " Confirme seu CPF.",
        ):
            with self.subTest(addition=addition):
                result = self.infer_reply("Sim", prompt=self.combined_prompt + addition)
                self.assertNotIn("opt_in_lgpd", result)
                self.assertNotIn("maior_de_18_anos", result)
                self.assertNotIn("marketing_opt_in", result)

    def test_combined_prompt_session_boundary_applies_to_both_decisions(self):
        messages = [
            self.message(0, self.combined_prompt, direction="out"),
            self.message(
                1,
                "Sim",
                after=timedelta(hours=WENI_UPDATE_CONTEXT_LOOKBACK_HOURS, seconds=1),
            ),
        ]
        result = infer_contact_fields(messages, candidate_message_ids={"1"})
        self.assertNotIn("opt_in_lgpd", result)
        self.assertNotIn("maior_de_18_anos", result)


if __name__ == "__main__":
    unittest.main()
