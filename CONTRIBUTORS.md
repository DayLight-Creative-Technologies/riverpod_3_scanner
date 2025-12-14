# Contributors

## Creator & Maintainer

**Steven Day**
- Role: Creator, Lead Developer, Maintainer
- Company: DayLight Creative Technologies
- Email: support@daylightcreative.tech
- GitHub: [@DayLight-Creative-Technologies](https://github.com/DayLight-Creative-Technologies)

## Project History

This scanner was developed by Steven Day at DayLight Creative Technologies while building SocialScoreKeeper, a Flutter-based sports app using Riverpod 3.0. After encountering multiple production crashes from unmounted provider references (47 crashes in 3 days from a single violation type), Steven created this comprehensive static analysis tool to prevent these issues across the entire codebase.

**Initial Development**: November 2025
**Production Deployment**: December 2025
**Public Release**: December 14, 2025

## Acknowledgments

### Technical Foundation
- **Riverpod Team** - For creating the `ref.mounted` feature in Riverpod 3.0 and establishing the official async safety pattern
- **Andrea Bizzotto** - For educational content on AsyncNotifier safety and mounted checks
- **Remi Rousselet** - Creator of Riverpod and provider ecosystem

### Real-World Validation
- **SocialScoreKeeper Team** - Production testing on 200k+ lines of Dart code
- **Flutter Community** - Crash reports and real-world failure scenarios that informed violation detection
- **Sentry** - Crash analytics that identified specific production failure patterns

## Contributing

We welcome contributions from the community! If you'd like to contribute:

1. **Report Issues**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/issues
2. **Feature Requests**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/discussions
3. **Pull Requests**: Fork the repo, create a feature branch, and submit a PR

### Contribution Guidelines

- Include test cases for new violation types
- Update documentation (GUIDE.md, EXAMPLES.md) with examples
- Follow existing code style and architecture patterns
- Add entries to CHANGELOG.md
- Ensure zero false positives (validate with real codebases)

## Future Contributors

If you contribute code, documentation, or significant testing, please add yourself here:

```markdown
**Your Name**
- Contribution: [Brief description]
- GitHub: [@username](https://github.com/username)
```

---

**Thank you to everyone who uses, tests, and improves this tool!**

*Created with ❤️ by Steven Day at DayLight Creative Technologies*
