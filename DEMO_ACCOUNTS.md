# Demo / Test Accounts

> **For development and testing purposes only.**
> These credentials are **not displayed** in the application UI.
> Add new accounts directly via the database.

## Manager

| Field    | Value                    |
|----------|--------------------------|
| Email    | manager@example.com      |
| Password | manager123               |
| Role     | manager                  |

## Workers

| Name  | Email              | Password  | Role   |
|-------|--------------------|-----------|--------|
| Priya | priya@example.com  | priya123  | worker |
| John  | john@example.com   | john123   | worker |

---

## Adding New Accounts

Insert directly into the `workers` table in MySQL:

```sql
INSERT INTO workers (name, email, password, role, avatar_color)
VALUES ('New Worker', 'worker@example.com', 'password123', 'worker', '#6366f1');
```

Available roles: `manager`, `worker`
