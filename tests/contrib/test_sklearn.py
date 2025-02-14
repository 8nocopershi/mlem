import posixpath

import lightgbm as lgb
import numpy as np
import pytest
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC

from mlem.api import apply, load_meta, save
from mlem.constants import PREDICT_METHOD_NAME, TRANSFORM_METHOD_NAME
from mlem.contrib.numpy import NumpyNdarrayType
from mlem.contrib.scipy import ScipySparseMatrix
from mlem.contrib.sklearn import SklearnModel, SklearnTransformer
from mlem.core.artifacts import LOCAL_STORAGE
from mlem.core.data_type import DataAnalyzer
from mlem.core.model import Argument, ModelAnalyzer
from mlem.core.objects import MlemModel
from mlem.core.requirements import UnixPackageRequirement
from tests.conftest import long


@pytest.fixture
def text_inp_data():
    return [
        "This is the first document.",
        "This document is the second document.",
    ]


@pytest.fixture
def inp_data():
    return [[1, 2, 3], [3, 2, 1]]


@pytest.fixture
def out_data():
    return [1, 2]


@pytest.fixture
def classifier(inp_data, out_data):
    lr = LogisticRegression()
    lr.fit(inp_data, out_data)
    return lr


@pytest.fixture
def regressor(inp_data, out_data):
    lr = LinearRegression()
    lr.fit(inp_data, out_data)
    return lr


@pytest.fixture
def count_vectorizer(text_inp_data):
    vectorizer = CountVectorizer()
    vectorizer.fit(text_inp_data)
    return vectorizer


@pytest.fixture
def transformer(inp_data):
    tf_idf = TfidfTransformer()
    tf_idf.fit(inp_data)
    return tf_idf


@pytest.fixture
def onehotencoder(inp_data):
    encoder = OneHotEncoder()
    encoder.fit(inp_data)
    return encoder


@pytest.fixture()
def pipeline(inp_data, out_data):
    pipe = Pipeline([("scaler", StandardScaler()), ("svc", SVC())])
    pipe.fit(inp_data, out_data)
    return pipe


@pytest.fixture
def lgbm_model(inp_data, out_data):
    lgbm_regressor = lgb.LGBMRegressor()
    return lgbm_regressor.fit(inp_data, out_data)


@pytest.mark.parametrize(
    "model_fixture", ["classifier", "regressor", "pipeline"]
)
def test_hook(model_fixture, inp_data, request):
    model = request.getfixturevalue(model_fixture)
    data_type = DataAnalyzer.analyze(inp_data)
    model_type = ModelAnalyzer.analyze(model, sample_data=inp_data)

    assert isinstance(model_type, SklearnModel)
    returns = NumpyNdarrayType(
        shape=(None,),
        dtype=model.predict(inp_data).dtype.name,
    )
    assert PREDICT_METHOD_NAME in model_type.methods
    signature = model_type.methods[PREDICT_METHOD_NAME]
    assert signature.name == PREDICT_METHOD_NAME
    assert signature.args[0] == Argument(name="X", type_=data_type)
    assert signature.returns == returns


@pytest.mark.parametrize(
    "transformer_fixture", ["transformer", "onehotencoder", "count_vectorizer"]
)
def test_hook_transformer(
    transformer_fixture, inp_data, text_inp_data, request
):
    transformer = request.getfixturevalue(transformer_fixture)
    if transformer_fixture == "count_vectorizer":
        input_data = text_inp_data
        argname = "raw_documents"
    else:
        input_data = inp_data
        argname = "X"
    data_type = DataAnalyzer.analyze(input_data)
    model_type = ModelAnalyzer.analyze(transformer, sample_data=input_data)
    assert isinstance(model_type, SklearnTransformer)
    assert TRANSFORM_METHOD_NAME in model_type.methods
    signature = model_type.methods[TRANSFORM_METHOD_NAME]
    cols = len(transformer.get_feature_names_out())
    rows = len(input_data)
    if transformer_fixture == "count_vectorizer":
        returns = ScipySparseMatrix(dtype="int64", shape=(rows, cols))
    else:
        returns = ScipySparseMatrix(dtype="float64", shape=(rows, cols))
    assert signature.name == TRANSFORM_METHOD_NAME
    assert signature.args[0] == Argument(name=argname, type_=data_type)
    assert signature.returns == returns


@pytest.mark.parametrize(
    "transformer_fixture", ["transformer", "onehotencoder", "count_vectorizer"]
)
def test_model_type__transform(
    transformer_fixture, inp_data, text_inp_data, request
):
    transformer = request.getfixturevalue(transformer_fixture)
    if transformer_fixture == "count_vectorizer":
        input_data = text_inp_data
    else:
        input_data = inp_data
    model_type = ModelAnalyzer.analyze(transformer, sample_data=input_data)

    np.testing.assert_array_almost_equal(
        transformer.transform(input_data).todense(),
        model_type.call_method("transform", input_data).todense(),
    )


@pytest.mark.parametrize(
    "transformer_fixture", ["transformer", "onehotencoder"]
)
def test_preprocess_transformer(
    classifier, transformer_fixture, inp_data, tmpdir, out_data, request
):
    transformer = request.getfixturevalue(transformer_fixture)
    model_file = "clf"
    clf = LogisticRegression()
    train_data = transformer.transform(inp_data)
    clf.fit(train_data, out_data)
    save(
        clf,
        str(tmpdir / model_file),
        sample_data=inp_data,
        preprocess=transformer,
    )
    clf = load_meta(str(tmpdir / model_file))
    output = apply(clf, inp_data)
    assert np.array_equal(output, out_data)


def test_hook_lgb(lgbm_model, inp_data):
    data_type = DataAnalyzer.analyze(inp_data)
    model_type = ModelAnalyzer.analyze(lgbm_model, sample_data=inp_data)

    assert isinstance(model_type, SklearnModel)

    returns = NumpyNdarrayType(
        shape=(None,),
        dtype="float64",
    )
    assert PREDICT_METHOD_NAME in model_type.methods
    signature = model_type.methods[PREDICT_METHOD_NAME]
    assert signature.name == PREDICT_METHOD_NAME
    assert signature.args[0] == Argument(name="X", type_=data_type)
    assert signature.returns == returns


@pytest.mark.parametrize("model", ["classifier", "regressor", "pipeline"])
def test_model_type__predict(model, inp_data, request):
    model = request.getfixturevalue(model)
    model_type = ModelAnalyzer.analyze(model, sample_data=inp_data)

    np.testing.assert_array_almost_equal(
        model.predict(inp_data), model_type.call_method("predict", inp_data)
    )


def test_model_type__clf_predict_proba(classifier, inp_data):
    model_type = ModelAnalyzer.analyze(classifier, sample_data=inp_data)

    np.testing.assert_array_almost_equal(
        classifier.predict_proba(inp_data),
        model_type.call_method("predict_proba", inp_data),
    )


def test_model_type__reg_predict_proba(regressor, inp_data):
    model_type = ModelAnalyzer.analyze(regressor, sample_data=inp_data)

    with pytest.raises(ValueError):
        model_type.call_method("predict_proba", inp_data)


@pytest.mark.parametrize("model", ["classifier", "regressor"])
def test_model_type__dump_load(tmpdir, model, inp_data, request):
    model = request.getfixturevalue(model)
    model_type = ModelAnalyzer.analyze(model, sample_data=inp_data)

    expected_requirements = {"sklearn", "numpy"}
    assert set(model_type.get_requirements().modules) == expected_requirements
    artifacts = model_type.dump(LOCAL_STORAGE, posixpath.join(tmpdir, "model"))
    model_type.model = None

    with pytest.raises(ValueError):
        model_type.call_method("predict", inp_data)

    model_type.load(artifacts)
    np.testing.assert_array_almost_equal(
        model.predict(inp_data), model_type.call_method("predict", inp_data)
    )
    assert set(model_type.get_requirements().modules) == expected_requirements


@long
def test_model_type_lgb__dump_load(tmpdir, lgbm_model, inp_data):
    model_type = ModelAnalyzer.analyze(lgbm_model, sample_data=inp_data)

    expected_requirements = {"sklearn", "lightgbm", "numpy"}
    reqs = model_type.get_requirements().expanded
    assert set(reqs.modules) == expected_requirements
    assert reqs.of_type(UnixPackageRequirement) == [
        UnixPackageRequirement(package_name="libgomp1")
    ]
    artifacts = model_type.dump(LOCAL_STORAGE, str(tmpdir / "model"))
    model_type.model = None

    with pytest.raises(ValueError):
        model_type.call_method("predict", inp_data)

    model_type.load(artifacts)
    np.testing.assert_array_almost_equal(
        lgbm_model.predict(inp_data),
        model_type.call_method("predict", inp_data),
    )
    reqs = model_type.get_requirements().expanded
    assert set(reqs.modules) == expected_requirements
    assert reqs.of_type(UnixPackageRequirement) == [
        UnixPackageRequirement(package_name="libgomp1")
    ]


def test_pipeline_requirements(lgbm_model, inp_data):
    model = Pipeline(steps=[("model", lgbm_model)])
    meta = MlemModel.from_obj(model)

    expected_requirements = {"sklearn", "lightgbm"}
    assert set(meta.requirements.modules) == expected_requirements

    meta = MlemModel.from_obj(model, sample_data=np.array(inp_data))

    expected_requirements = {"sklearn", "lightgbm", "numpy"}
    assert set(meta.requirements.modules) == expected_requirements


# Copyright 2019 Zyfra
# Copyright 2021 Iterative
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
