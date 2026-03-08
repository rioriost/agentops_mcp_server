class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/d9/52/509e3d42d69e9183a64c28af3a428dbef7ae280e44c582c7e8e55c8e0f0d/agentops_mcp_server-0.4.12.tar.gz"
  sha256 "35b948589a51e47e5a38d1a477b53b04cf38b784a01433b3d8939dfc90c75bb2"
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
