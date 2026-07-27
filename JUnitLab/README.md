# BankAccount JUnit 实验

本目录对应课程要求中的 `BankAccount.java` 和 `BankAccountTest.java`。

运行测试并生成 JUnit XML、JaCoCo HTML/XML 覆盖率报告：

```bash
mvn clean test
```

报告位置：

- `reports/test/`
- `reports/coverage/index.html`
- `reports/coverage/jacoco.xml`

`oneThousandWithdrawalsAreMeasured` 测试会输出 1000 次取款耗时。
