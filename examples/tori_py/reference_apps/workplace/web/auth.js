import Keycloak from "/assets/keycloak.js";

export function createKeycloak() {
  return new Keycloak({
    url: "http://localhost:8080",
    realm: "tori-space",
    clientId: "tori-space-web",
  });
}
