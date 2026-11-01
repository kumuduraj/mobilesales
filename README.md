### Mobile Sales

Mobile Billing / van sales for ERPNext: stock issue to sales agents, customer visits,
invoicing and collection on the road, end-of-day settlement and reports.

### Requirements

- Frappe Framework v16
- ERPNext v16

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app git@github-mobilesales:kumuduraj/mobilesales.git --branch main
bench --site <site> install-app mobilesales && bench --site <site> migrate
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/mobilesales
pre-commit install
```

### License

MIT
