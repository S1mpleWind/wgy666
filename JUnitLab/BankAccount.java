public class BankAccount {
    private String owner;
    private double balance;

    public static class InsufficientFundsException extends Exception {
        public InsufficientFundsException(String message) {
            super(message);
        }
    }

    public BankAccount(String owner, double initialBalance) {
        this.owner = owner;
        this.balance = initialBalance;
    }

    public BankAccount(String owner) {
        this(owner, 0.0);
    }

    public double deposit(double amount) throws IllegalArgumentException {
        if (amount <= 0) {
            throw new IllegalArgumentException("Deposit amount must be positive.");
        }
        this.balance += amount;
        return this.balance;
    }

    public double withdraw(double amount)
            throws InsufficientFundsException, IllegalArgumentException {
        if (amount <= 0) {
            throw new IllegalArgumentException("Withdrawal amount must be positive.");
        }
        if (amount > this.balance) {
            throw new InsufficientFundsException(
                    "Insufficient funds to complete the withdrawal.");
        }
        this.balance -= amount;
        return this.balance;
    }

    public double getBalance() {
        return this.balance;
    }

    public void transfer(double amount, BankAccount targetAccount)
            throws InsufficientFundsException, IllegalArgumentException {
        this.withdraw(amount);
        targetAccount.deposit(amount);
    }

    @Override
    public String toString() {
        return "BankAccount of " + this.owner + " with balance: $"
                + String.format("%.2f", this.balance);
    }
}
