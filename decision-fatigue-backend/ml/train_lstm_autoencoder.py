import tensorflow as tf
import numpy as np
from utils import load_data

SEQUENCE_LENGTH = 5
LATENT_DIM = 16
EPOCHS = 40
BATCH_SIZE = 16

# Load data
X = load_data()

mean = X.mean(axis=0)
std = X.std(axis=0) + 1e-6
X_norm = (X - mean) / std

# Build sequences
sequences = []
for i in range(len(X_norm) - SEQUENCE_LENGTH):
    sequences.append(X_norm[i:i + SEQUENCE_LENGTH])

X_seq = np.array(sequences)

# Model
inputs = tf.keras.Input(shape=(SEQUENCE_LENGTH, X_seq.shape[2]))

encoded = tf.keras.layers.LSTM(LATENT_DIM, activation="tanh")(inputs)
decoded = tf.keras.layers.RepeatVector(SEQUENCE_LENGTH)(encoded)
decoded = tf.keras.layers.LSTM(
    X_seq.shape[2], activation="tanh", return_sequences=True
)(decoded)
outputs = tf.keras.layers.TimeDistributed(
    tf.keras.layers.Dense(X_seq.shape[2])
)(decoded)

model = tf.keras.Model(inputs, outputs)
model.compile(optimizer="adam", loss="mse")

model.summary()

# Train
model.fit(
    X_seq,
    X_seq,
    epochs=EPOCHS,
    batch_size=BATCH_SIZE,
    validation_split=0.1,
    callbacks=[
        tf.keras.callbacks.EarlyStopping(
            patience=5,
            restore_best_weights=True
        )
    ]
)

# Reconstruction error
recon = model.predict(X_seq, verbose=0)
errors = np.mean((X_seq - recon) ** 2, axis=(1, 2))
threshold = np.percentile(errors, 95)

# Save
model.save("lstm_autoencoder.h5")
np.save("lstm_mean.npy", mean)
np.save("lstm_std.npy", std)
np.save("lstm_threshold.npy", threshold)

print("✅ LSTM Autoencoder trained successfully")
print("Threshold:", threshold)
