import numpy as np
from sklearn.linear_model import LogisticRegression

class PricePredictionModel:
    def __init__(self):
        # Initial training data: [RSI, MACD, Momentum] -> Target (1 for Up, 0 for Down)
        X_train = np.array([
            [55, 0.8, 1.2],
            [60, 0.9, 1.5],
            [68, 1.1, 2.0],
            [40, -0.2, 0.5],
            [35, -0.5, 0.2],
            [45, 0.1, 0.8]
        ])
        y_train = np.array([1, 1, 1, 0, 0, 0]) # 1 = Bullish/Up, 0 = Bearish/Down
        
        self.model = LogisticRegression()
        self.model.fit(X_train, y_train)

    def predict_trend(self, rsi: float, macd: float, momentum: float) -> int:
        """
        Predicts whether the market direction will be bullish (1) or bearish (0)
        using machine learning based on current indicators.
        """
        features = np.array([[rsi, macd, momentum]])
        prediction = self.model.predict(features)
        return int(prediction[0])

if __name__ == "__main__":
    ml = PricePredictionModel()
    test_pred = ml.predict_trend(65, 1.0, 1.8)
    print(f"ML Model Test Prediction (1=Up, 0=Down): {test_pred}")