use crate::build_metadata::EMBEDDED_API_KEY;

#[derive(Clone, Copy)]
pub struct EmbeddedApiKey(&'static str);

impl EmbeddedApiKey {
    #[must_use]
    pub const fn expose_for_transport(self) -> &'static str {
        self.0
    }
}

#[must_use]
pub const fn embedded_api_key() -> Option<EmbeddedApiKey> {
    Some(EmbeddedApiKey(EMBEDDED_API_KEY))
}

#[must_use]
pub fn redact_secret(message: &str, secret: EmbeddedApiKey) -> String {
    message.replace(secret.expose_for_transport(), "[REDACTED]")
}

#[cfg(test)]
mod tests {
    use super::{embedded_api_key, redact_secret};

    const DEBUG_KEY: &str = "desktop-debug-key-not-a-real-secret";

    #[test]
    fn embedded_api_key_is_available_without_external_env() {
        let key = embedded_api_key();

        assert_eq!(
            key.map(super::EmbeddedApiKey::expose_for_transport),
            Some(DEBUG_KEY)
        );
    }

    #[test]
    fn errors_and_logs_redact_service_key() {
        let key = super::EmbeddedApiKey(DEBUG_KEY);
        let message = format!("request failed for serviceKey={DEBUG_KEY}");

        assert_eq!(
            redact_secret(&message, key),
            "request failed for serviceKey=[REDACTED]"
        );
    }
}
