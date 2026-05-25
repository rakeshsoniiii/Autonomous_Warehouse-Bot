import tensorflow as tf
from tensorflow.keras import layers
from tensorflow.keras.models import Sequential

# IMAGE SETTINGS
img_size = 224
batch_size = 16

# LOAD DATASET
train_ds = tf.keras.preprocessing.image_dataset_from_directory(
    "DATASET",
    validation_split=0.2,
    subset="training",
    seed=123,
    image_size=(img_size, img_size),
    batch_size=batch_size
)

val_ds = tf.keras.preprocessing.image_dataset_from_directory(
    "DATASET",
    validation_split=0.2,
    subset="validation",
    seed=123,
    image_size=(img_size, img_size),
    batch_size=batch_size
)

# OPTIMIZE DATASET
AUTOTUNE = tf.data.AUTOTUNE

train_ds = train_ds.prefetch(buffer_size=AUTOTUNE)
val_ds = val_ds.prefetch(buffer_size=AUTOTUNE)

# PRETRAINED MODEL
base_model = tf.keras.applications.MobileNetV2(

    input_shape=(224,224,3),
    include_top=False,
    weights="imagenet"
)

# FREEZE MODEL
base_model.trainable = False

# FINAL MODEL
model = Sequential([

    # NORMALIZATION
    layers.Rescaling(1./255),

    # FEATURE EXTRACTOR
    base_model,

    # CLASSIFICATION
    layers.GlobalAveragePooling2D(),

    layers.Dense(128, activation='relu'),

    layers.Dropout(0.3),

    layers.Dense(3, activation='softmax')
])

# COMPILE
model.compile(

    optimizer='adam',

    loss='sparse_categorical_crossentropy',

    metrics=['accuracy']
)

# TRAIN
model.fit(

    train_ds,

    validation_data=val_ds,

    epochs=10
)

# SAVE MODEL
model.save("warehouse_ai_model.h5")

print("MODEL TRAINED SUCCESSFULLY")