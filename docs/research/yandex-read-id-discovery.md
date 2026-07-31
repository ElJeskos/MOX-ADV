# Read-only discovery of Yandex campaign and goal IDs

Verified against official Yandex documentation on 2026-07-30.
No credentials were accessed and no API requests were sent.

## Yandex Direct campaign IDs

The current Campaigns service documentation lists the production JSON endpoint as `https://api.direct.yandex.com/json/v501/campaigns`.
Yandex Direct sends every API operation over HTTPS with HTTP `POST`, while the JSON body's `method` value selects the semantic operation.
Consequently, a request whose body contains `"method": "get"` is a semantic read even though its transport verb is `POST`.

The request must include `Authorization: Bearer <token>` and a JSON content type.
`Client-Login` is required when an agency makes the request on behalf of an advertiser.
`Accept-Language` is optional.

`FieldNames` is required.
`SelectionCriteria` and `SelectionCriteria.Ids` are optional.
For discovery, the documented safe and explicit form is an empty `SelectionCriteria` object, which returns the campaigns available in the selected OAuth and `Client-Login` account context.

```http
POST https://api.direct.yandex.com/json/v501/campaigns
Authorization: Bearer <token>
Client-Login: <advertiser-login>
Content-Type: application/json; charset=utf-8
```

```json
{
  "method": "get",
  "params": {
    "SelectionCriteria": {},
    "FieldNames": ["Id", "Name", "Type", "Status", "State"]
  }
}
```

`Id` and `Name` are sufficient for a minimal picker.
Adding `Type`, `Status`, and `State` makes the choice understandable without requesting campaign-type-specific settings.
The IDs are returned in `result.Campaigns[].Id`.
The method returns at most 10,000 campaigns, and a returned `result.LimitedBy` means that pagination is required.

Official sources:

- [Campaigns service and current production JSON address](https://yandex.com/dev/direct/doc/en/campaigns/campaigns)
- [Campaigns.get request, optional selection criteria, fields, and response](https://yandex.com/dev/direct/doc/en/campaigns/get)
- [Direct interaction format and POST transport](https://yandex.com/dev/direct/doc/en/concepts/format)
- [Direct HTTP headers](https://yandex.com/dev/direct/doc/en/concepts/headers)
- [Direct access and authorization](https://yandex.com/dev/direct/doc/en/concepts/access)

## Yandex Metrica goal IDs

For a known counter, the Management API exposes the goal collection as an HTTPS `GET`, so both the HTTP transport and the semantic operation are read-only.
The request needs `Authorization: OAuth <token>`.
A token with `metrika:read` is sufficient for reading owned or delegated counters, provided that the token's account has access to the counter.
The optional `useDeleted` query parameter defaults to `false`.

```http
GET https://api-metrika.yandex.net/management/v1/counter/{counterId}/goals
Authorization: OAuth <token>
```

The response contains a `goals` array.
The common useful fields are `id`, `name`, `type`, `status`, `goal_source`, `default_price`, and `is_favorite`.
Depending on the goal type, the response may also contain fields such as `conditions`, `steps`, `depth`, or `duration`.
The goal ID needed by MOX-ADV is returned as `goals[].id`.

Official sources:

- [List of goals for a counter](https://yandex.com/dev/metrika/en/management/openapi/goal/goals)
- [Metrica authorization and the `metrika:read` scope](https://yandex.com/dev/metrika/en/intro/authorization)
- [Metrica resource methods and GET read semantics](https://yandex.com/dev/metrika/en/intro/method-call)
