import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

class BankAccountTest {
    private static final double EPSILON = 0.000001;

    @Test
    void defaultConstructorStartsWithZeroBalance() {
        BankAccount account = new BankAccount("Alice");

        assertEquals(0.0, account.getBalance(), EPSILON);
    }

    @Test
    void depositAddsMoneyAndReturnsNewBalance() {
        BankAccount account = new BankAccount("Alice", 100.0);

        assertEquals(150.0, account.deposit(50.0), EPSILON);
        assertEquals(150.0, account.getBalance(), EPSILON);
    }

    @Test
    void depositRejectsZeroAndNegativeAmounts() {
        BankAccount account = new BankAccount("Alice");

        assertThrows(IllegalArgumentException.class, () -> account.deposit(0.0));
        assertThrows(IllegalArgumentException.class, () -> account.deposit(-1.0));
    }

    @Test
    void withdrawSubtractsMoneyAndReturnsNewBalance() throws Exception {
        BankAccount account = new BankAccount("Alice", 100.0);

        assertEquals(60.0, account.withdraw(40.0), EPSILON);
        assertEquals(60.0, account.getBalance(), EPSILON);
    }

    @Test
    void withdrawRejectsZeroAndNegativeAmounts() {
        BankAccount account = new BankAccount("Alice", 100.0);

        assertThrows(IllegalArgumentException.class, () -> account.withdraw(0.0));
        assertThrows(IllegalArgumentException.class, () -> account.withdraw(-1.0));
    }

    @Test
    void withdrawRejectsInsufficientFunds() {
        BankAccount account = new BankAccount("Alice", 20.0);

        assertThrows(BankAccount.InsufficientFundsException.class,
                () -> account.withdraw(20.01));
        assertEquals(20.0, account.getBalance(), EPSILON);
    }

    @Test
    void transferMovesMoneyBetweenAccounts() throws Exception {
        BankAccount source = new BankAccount("Alice", 100.0);
        BankAccount target = new BankAccount("Bob", 25.0);

        source.transfer(40.0, target);

        assertEquals(60.0, source.getBalance(), EPSILON);
        assertEquals(65.0, target.getBalance(), EPSILON);
    }

    @Test
    void failedTransferDoesNotChangeEitherAccount() {
        BankAccount source = new BankAccount("Alice", 10.0);
        BankAccount target = new BankAccount("Bob", 25.0);

        assertThrows(BankAccount.InsufficientFundsException.class,
                () -> source.transfer(11.0, target));
        assertEquals(10.0, source.getBalance(), EPSILON);
        assertEquals(25.0, target.getBalance(), EPSILON);
    }

    @Test
    void toStringIncludesOwnerAndFormattedBalance() {
        BankAccount account = new BankAccount("Alice", 12.5);

        assertEquals("BankAccount of Alice with balance: $12.50", account.toString());
    }

    @Test
    void oneThousandWithdrawalsAreMeasured() throws Exception {
        BankAccount account = new BankAccount("Performance", 1000.0);
        long start = System.nanoTime();

        for (int i = 0; i < 1000; i++) {
            account.withdraw(1.0);
        }

        long elapsedNanos = System.nanoTime() - start;
        double elapsedMilliseconds = elapsedNanos / 1_000_000.0;
        System.out.printf("1000 withdrawals: %.3f ms%n", elapsedMilliseconds);
        String report = "BankAccount 性能测试报告\n"
                + "========================\n"
                + "测试操作：取款 1000 次\n"
                + String.format("总耗时：%.3f ms\n", elapsedMilliseconds)
                + String.format("最终余额：%.2f\n", account.getBalance())
                + "结果：通过\n";
        try {
            Path reportPath = Path.of("reports", "performance-report.txt");
            Files.createDirectories(reportPath.getParent());
            Files.writeString(reportPath, report);
        } catch (java.io.IOException exception) {
            throw new AssertionError("无法写入性能报告", exception);
        }
        assertEquals(0.0, account.getBalance(), EPSILON);
    }
}
