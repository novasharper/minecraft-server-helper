from pydantic import BaseModel


class ServerConfig(BaseModel):
    pass


class ModpackConfig(BaseModel):
    pass


class ModsConfig(BaseModel):
    pass


class RootConfig(BaseModel):
    server: ServerConfig
