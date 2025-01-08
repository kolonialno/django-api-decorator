<h1 align="center">
  Django API Decorator
</h1>

<p align="center">
  A collection of tools to build function based Django APIs.
</p>

> **Warning**
> This project is still in early development. Expect breaking changes.

## Installation

Django API Decorator can be installed from
[PyPI](https://pypi.org/project/django-api-decorator):

`pip install django-api-decorator`


## Usage

The main interface of this library is the `@api` decorator. This handles input
and output from your view, according to type annotations on the view. Pydantic
is used to handle most of the encoding and decoding, but you are not limited to
use pydantic models for your types. You can use any type supported by pydantic,
from simple types to dataclasses and typed dicts.

Here's a simple example:

```python
@api(method="GET")
def list_some_numbers(request: HttpRequest) -> list[int]:
    return [1, 2, 3, 4]
```

Under the hood the `@api` decorator will encode the list of numbers ot JSON and
wrap it up in a response object for Django to handle like any other response.

You can also specify query parameters, that will be decoded according to the
specified type annotations:

```python
@api(method="GET", query_params=["count"])
def list_some_numbers(request: HttpRequest, count: int) -> list[int]:
    return [random.randint(0, 10) for _ in range(count)]
```

Here the decorator will extract the `count` query paramter from the request and
make sure it's a valid integer.

The decorator can also decode the request body for you:

```python
@api(method="POST")
def sum_of_numbers(request: HttpRequest, body: list[int]) -> int:
    return sum(body)
```

The views produced by the decorator are plain Django views and should be added
in your urls module just like any other view:

```python
urlpatterns = [
    path("/api/numbers/", list_some_numbers, name="list-some-numbers"),
]
```

If you want to handle multiple methods on the same url a `method_router` helper
function is provided, which can be used like this:

```python
urlpatterns = [
    path(
        "/api/numbers/",
        method_router(
            GET=list_some_numbers,
            POST=...
        ),
        name="list-some-numbers",
    ),
]
```


## OpenAPI specification

This library can also generate an OpenAPI specification from your views. This
is done by inspecting the urlpatterns of the Django project, finding all views
using the `@api` decorator. The schema for the specification is generated using
pydantic, so for details about how different types are treated see [Pydantic's
documentation](https://docs.pydantic.dev/latest/usage/json_schema/).

The specification is generated using the `generate_api_schemas` management
command.

### Control Operations Included in the Schema

Controlling which operations are included in the generated schema can be useful.
Your application might depend on libraries that also use the `django-api-decorator`
package to build APIs, and you may prefer not to include those in your schema.

This is achieved by defining a set of tags on each view method.

```python
@api(method="GET", tags=["django-api-decorator"])
def view(request: HttpRequest) -> None:
    ...
```

Views without the tags property set will always be included in the schema.

You can either exclude tags you don't want in your schema or select tags you
want to include. However, you cannot both include and exclude tags simultaneously.

#### Including Tags in the Schema

Specify the tags to include in your schema in the Django settings file:

```python
API_DECORATOR_SCHEMA_INCLUDE_TAGS = ["app", ...]
```

#### Excluding Tags from the Schema

Specify the tags to exclude from your schema in the Django settings file:

```python
API_DECORATOR_SCHEMA_EXCLUDE_TAGS = ["library", ...]
```
