class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/50/8f/55138e91987ccb19a1754a8fbdd47221943060d94a458e257f10b82e8dcb/agentops_mcp_server-0.5.1.tar.gz"
  sha256 "5ba954efddb50a22d2c50b20835b2830dce9aea6a011758f767b639433c696d7"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
